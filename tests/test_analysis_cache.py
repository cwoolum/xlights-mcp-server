"""Tests for analysis result caching and stage progress in full_analysis."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.audio import analyzer
from xlights_mcp.audio.analyzer import full_analysis
from xlights_mcp.config import AudioConfig


def _config(tmp_path: Path) -> AudioConfig:
    return AudioConfig(cache_dir=tmp_path / "cache")


def test_full_analysis_reports_each_stage(click_track: Path, tmp_path: Path):
    events: list[tuple[int, int, str]] = []

    analysis = full_analysis(
        click_track, _config(tmp_path), progress=lambda i, n, msg: events.append((i, n, msg))
    )

    assert analysis.duration_seconds == pytest.approx(3.0, abs=0.1)
    messages = [m for _, _, m in events]
    assert any("beat" in m.lower() for m in messages)
    assert any("spectrum" in m.lower() for m in messages)
    assert any("structure" in m.lower() for m in messages)
    # Counters are monotonic and end at total
    assert [i for i, _, _ in events] == sorted(i for i, _, _ in events)
    assert events[-1][0] == events[-1][1]


def test_full_analysis_second_call_served_from_cache(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = _config(tmp_path)
    first = full_analysis(click_track, config)
    assert first.cached is False

    def boom(*_args, **_kwargs):
        raise AssertionError("analysis re-ran despite cache")

    monkeypatch.setattr(analyzer, "detect_beats", boom)
    monkeypatch.setattr(analyzer, "analyze_spectrum", boom)
    monkeypatch.setattr(analyzer, "detect_structure", boom)

    second = full_analysis(click_track, config)
    assert second.cached is True
    assert second.beats == first.beats
    assert second.sections == first.sections


def test_cache_invalidated_when_audio_changes(click_track: Path, tmp_path: Path):
    config = _config(tmp_path)
    full_analysis(click_track, config)

    # Truncate the file so its content hash changes
    data = click_track.read_bytes()
    click_track.write_bytes(data[: len(data) // 2])

    again = full_analysis(click_track, config)
    assert again.cached is False


def test_force_bypasses_cache(click_track: Path, tmp_path: Path):
    config = _config(tmp_path)
    full_analysis(click_track, config)

    again = full_analysis(click_track, config, force=True)
    assert again.cached is False


def test_failed_stem_separation_is_not_cached(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from xlights_mcp.audio import cache

    config = _config(tmp_path)

    def boom(_path):
        raise RuntimeError("demucs blew up")

    monkeypatch.setattr(analyzer, "separate_stems", boom)

    analysis = full_analysis(click_track, config)

    assert analysis.stem_analysis.available is False
    assert not cache.cache_path(click_track, config.cache_dir).exists()


def test_failed_stem_analysis_is_not_cached(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from xlights_mcp.audio import cache
    from xlights_mcp.audio.separator import StemPaths

    config = _config(tmp_path)

    monkeypatch.setattr(analyzer, "separate_stems", lambda _p: StemPaths(available=True))

    def boom(_stems, sr):
        raise RuntimeError("librosa blew up")

    monkeypatch.setattr(analyzer, "analyze_stems", boom)

    analysis = full_analysis(click_track, config)

    assert analysis.stem_analysis.available is False
    assert not cache.cache_path(click_track, config.cache_dir).exists()


def test_stems_unavailable_without_error_is_still_cached(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from xlights_mcp.audio import cache
    from xlights_mcp.audio.separator import StemPaths

    config = _config(tmp_path)
    monkeypatch.setattr(analyzer, "separate_stems", lambda _p: StemPaths(available=False))

    full_analysis(click_track, config)

    assert cache.cache_path(click_track, config.cache_dir).exists()


def test_cache_ignores_entries_written_by_the_previous_version(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from xlights_mcp.audio import cache
    from xlights_mcp.audio.analyzer import SongAnalysis

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(cache, "ANALYSIS_VERSION", 1)
    cache.save_cached(SongAnalysis(file_path=str(click_track), file_name="click.wav"), click_track, cache_dir)
    assert cache.load_cached(click_track, cache_dir) is not None
    monkeypatch.undo()

    assert cache.load_cached(click_track, cache_dir) is None


def test_save_cached_writes_atomically_leaving_no_temp_file(
    click_track: Path, tmp_path: Path
):
    from xlights_mcp.audio import cache
    from xlights_mcp.audio.analyzer import SongAnalysis

    cache_dir = tmp_path / "cache"
    analysis = SongAnalysis(file_path=str(click_track), file_name="click.wav")

    path = cache.save_cached(analysis, click_track, cache_dir)

    assert path.exists()
    assert list(path.parent.iterdir()) == [path]


def test_save_cached_leaves_existing_entry_untouched_when_write_fails(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from xlights_mcp.audio import cache
    from xlights_mcp.audio.analyzer import SongAnalysis

    cache_dir = tmp_path / "cache"
    first = SongAnalysis(file_path=str(click_track), file_name="click.wav", duration_seconds=1.0)
    path = cache.save_cached(first, click_track, cache_dir)
    original_bytes = path.read_bytes()

    second = SongAnalysis(file_path=str(click_track), file_name="click.wav", duration_seconds=2.0)

    def boom(self) -> str:
        raise RuntimeError("disk full")

    monkeypatch.setattr(SongAnalysis, "model_dump_json", boom)

    with pytest.raises(RuntimeError, match="disk full"):
        cache.save_cached(second, click_track, cache_dir)

    assert path.read_bytes() == original_bytes
    assert list(path.parent.iterdir()) == [path]
