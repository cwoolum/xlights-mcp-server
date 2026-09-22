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
