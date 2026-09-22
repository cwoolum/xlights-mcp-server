"""End-to-end tests for the analyze_song MCP tool via an in-memory client session."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from drum_fixtures import make_drum_stem
from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
from xlights_mcp.audio.analyzer import SongAnalysis, StemAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.cache import save_cached
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.config import AudioConfig, ServerConfig


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServerConfig:
    config = ServerConfig(audio=AudioConfig(cache_dir=tmp_path / "cache"))
    monkeypatch.setattr(server_module, "_config", config)
    return config


async def _call_analyze(path: Path, **extra):
    progress: list[tuple[float, float | None, str | None]] = []

    async def on_progress(p: float, total: float | None, message: str | None) -> None:
        progress.append((p, total, message))

    async with create_connected_server_and_client_session(server_module.mcp) as client:
        result = await client.call_tool(
            "analyze_song",
            {"mp3_path": str(path), **extra},
            progress_callback=on_progress,
        )
    payload = json.loads(result.content[0].text)
    return payload, progress


async def test_analyze_song_streams_progress_notifications(
    click_track: Path, isolated_config: ServerConfig
):
    payload, progress = await _call_analyze(click_track)

    assert "error" not in payload
    assert payload["cached"] is False
    messages = [m for _, _, m in progress]
    assert any("beat" in m.lower() for m in messages)
    assert progress[-1][0] == progress[-1][1]


async def test_analyze_song_returns_summary_not_raw_curves(
    click_track: Path, isolated_config: ServerConfig
):
    payload, _ = await _call_analyze(click_track)

    assert payload["duration_seconds"] == pytest.approx(3.0, abs=0.1)
    assert payload["beat_count"] > 0
    assert isinstance(payload["sections"], list)
    assert "elapsed_seconds" in payload
    # Raw per-frame arrays belong to get_beat_map / get_energy_profile
    assert "beats" not in payload
    assert "spectrum" not in payload


async def test_analyze_song_reports_cache_hit(click_track: Path, isolated_config: ServerConfig):
    await _call_analyze(click_track)
    payload, _ = await _call_analyze(click_track)

    assert payload["cached"] is True


async def test_analyze_song_force_reruns(click_track: Path, isolated_config: ServerConfig):
    await _call_analyze(click_track)
    payload, _ = await _call_analyze(click_track, force=True)

    assert payload["cached"] is False


async def _call(name: str, args: dict):
    progress: list[tuple[float, float | None, str | None]] = []

    async def on_progress(p: float, total: float | None, message: str | None) -> None:
        progress.append((p, total, message))

    async with create_connected_server_and_client_session(server_module.mcp) as client:
        result = await client.call_tool(name, args, progress_callback=on_progress)
    if result.isError:
        text = result.content[0].text if result.content else "<no content>"
        raise AssertionError(f"tool {name!r} returned an error result: {text}")
    return json.loads(result.content[0].text), progress


@pytest.mark.parametrize(
    ("tool", "key"),
    [("get_beat_map", "beat_times"), ("get_song_structure", "sections"), ("get_energy_profile", "rms_energy")],
)
async def test_detail_tools_served_from_analysis_cache(
    tool: str,
    key: str,
    click_track: Path,
    isolated_config: ServerConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    await _call_analyze(click_track)

    def boom(*_a, **_k):
        raise AssertionError("re-analyzed despite cache")

    from xlights_mcp.audio import analyzer, beats, spectrum, structure

    for mod in (analyzer, beats):
        monkeypatch.setattr(mod, "detect_beats", boom)
    for mod in (analyzer, spectrum):
        monkeypatch.setattr(mod, "analyze_spectrum", boom)
    for mod in (analyzer, structure):
        monkeypatch.setattr(mod, "detect_structure", boom)

    payload, _ = await _call(tool, {"mp3_path": str(click_track)})
    assert "error" not in payload
    assert key in payload


async def test_preview_plan_streams_progress(
    click_track: Path, isolated_config: ServerConfig, tmp_path: Path
):
    import shutil

    show = tmp_path / "show"
    show.mkdir()
    shutil.copy(Path("tests/fixtures/remapping/minimal_rgbeffects.xml"), show / "xlights_rgbeffects.xml")
    isolated_config.show_folders = {"test": str(show)}
    isolated_config.active_show = "test"

    payload, progress = await _call("preview_plan", {"mp3_path": str(click_track), "show_name": "test"})

    assert "error" not in payload
    assert any("beat" in (m or "").lower() for _, _, m in progress)


def _cache_fake_analysis(path: Path, config: ServerConfig, with_stems: bool = True) -> None:
    section = (
        SongSection(label="drop", start_time=0.0, end_time=20.0, structure_source="stems", drums="present")
        if with_stems
        else SongSection(label="drop", start_time=0.0, end_time=20.0, structure_source="mixdown", drums=None)
    )
    analysis = SongAnalysis(
        file_path=str(path),
        file_name=path.name,
        duration_seconds=20.0,
        beats=BeatMap(
            tempo=120.0,
            beat_times=np.arange(0, 20, 0.5).tolist(),
            downbeat_times=np.arange(0, 20, 2.0).tolist(),
            beat_source="madmom",
            drum_aligned=with_stems,
        ),
        sections=[section],
        stem_analysis=StemAnalysis(
            available=with_stems,
            stems={"drums": make_drum_stem([(0, 8), (12, 20)], duration=20.0)} if with_stems else {},
        ),
    )
    save_cached(analysis, path, config.audio.cache_dir)


async def test_analyze_song_reports_stem_summary_and_provenance(
    click_track: Path, isolated_config: ServerConfig
):
    _cache_fake_analysis(click_track, isolated_config)

    payload, _ = await _call_analyze(click_track)

    assert payload["beat_source"] == "madmom"
    assert payload["drum_aligned"] is True
    assert payload["structure_source"] == "stems"
    assert payload["stems"]["drums"]["onsets"] == 32
    assert payload["sections"][0]["drums"] == "present"
    silences_ms = payload["stems"]["drums"]["silences_ms"]
    assert silences_ms == [[7755, 12005]]
    assert all(isinstance(v, int) for span in silences_ms for v in span)


async def test_analyze_song_stems_null_without_separation(
    click_track: Path, isolated_config: ServerConfig
):
    _cache_fake_analysis(click_track, isolated_config, with_stems=False)

    payload, _ = await _call_analyze(click_track)

    assert payload["stems"] is None
    assert payload["structure_source"] == "mixdown"
    assert payload["sections"][0]["drums"] is None


async def test_analyze_song_structure_source_defaults_to_mixdown_without_sections(
    click_track: Path, isolated_config: ServerConfig
):
    analysis = SongAnalysis(
        file_path=str(click_track),
        file_name=click_track.name,
        duration_seconds=20.0,
        beats=BeatMap(
            tempo=120.0,
            beat_times=np.arange(0, 20, 0.5).tolist(),
            downbeat_times=np.arange(0, 20, 2.0).tolist(),
        ),
        sections=[],
    )
    save_cached(analysis, click_track, isolated_config.audio.cache_dir)

    payload, _ = await _call_analyze(click_track)

    assert payload["structure_source"] == "mixdown"


async def test_get_stem_events_serves_windowed_onsets(click_track: Path, isolated_config: ServerConfig):
    _cache_fake_analysis(click_track, isolated_config)

    payload, _ = await _call(
        "get_stem_events",
        {"mp3_path": str(click_track), "stem": "drums", "kind": "onsets", "start_ms": 1000, "end_ms": 3000},
    )

    assert payload["events_ms"] == [1000, 1500, 2000, 2500]


async def test_get_stem_events_rejects_bad_kind_before_analysing(
    click_track: Path, isolated_config: ServerConfig, monkeypatch
):
    def boom(*_a, **_k):
        raise AssertionError("analysed despite invalid arguments")

    monkeypatch.setattr(server_module, "_analyze_in_thread", boom)

    payload, _ = await _call("get_stem_events", {"mp3_path": str(click_track), "stem": "drums", "kind": "hits"})

    assert "onsets" in payload["error"]


async def test_get_stem_events_rejects_bad_max_events_before_analysing(
    click_track: Path, isolated_config: ServerConfig, monkeypatch
):
    def boom(*_a, **_k):
        raise AssertionError("analysed despite invalid arguments")

    monkeypatch.setattr(server_module, "_analyze_in_thread", boom)

    payload, _ = await _call(
        "get_stem_events",
        {"mp3_path": str(click_track), "stem": "drums", "kind": "onsets", "max_events": 0},
    )

    assert "max_events" in payload["error"]


async def test_get_stem_events_rejects_inverted_window_before_analysing(
    click_track: Path, isolated_config: ServerConfig, monkeypatch
):
    def boom(*_a, **_k):
        raise AssertionError("analysed despite invalid arguments")

    monkeypatch.setattr(server_module, "_analyze_in_thread", boom)

    payload, _ = await _call(
        "get_stem_events",
        {
            "mp3_path": str(click_track),
            "stem": "drums",
            "kind": "onsets",
            "start_ms": 3000,
            "end_ms": 1000,
        },
    )

    assert "start_ms" in payload["error"]
    assert "end_ms" in payload["error"]


async def test_get_stem_events_reports_error_when_stems_unavailable(
    click_track: Path, isolated_config: ServerConfig
):
    from xlights_mcp.audio.stem_events import STEMS_UNAVAILABLE

    _cache_fake_analysis(click_track, isolated_config, with_stems=False)

    payload, _ = await _call(
        "get_stem_events", {"mp3_path": str(click_track), "stem": "drums", "kind": "onsets"}
    )

    assert payload["error"] == STEMS_UNAVAILABLE
