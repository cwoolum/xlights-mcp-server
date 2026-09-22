"""End-to-end tests for the analyze_song MCP tool via an in-memory client session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
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
