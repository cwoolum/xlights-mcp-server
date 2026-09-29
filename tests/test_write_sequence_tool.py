"""write_sequence through an in-memory MCP session."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.cache import save_cached
from xlights_mcp.config import AudioConfig, ServerConfig

FIXTURE = Path(__file__).parent / "fixtures" / "show_groups"
PLAN = [{"element": "Door", "layer": 0, "effect": "On", "start_ms": 0, "end_ms": 1000}]


@pytest.fixture
def show(tmp_path: Path, click_track: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "show"
    folder.mkdir()
    shutil.copy(FIXTURE / "xlights_rgbeffects.xml", folder)
    config = ServerConfig(
        show_folders={"fixture": str(folder)},
        active_show="fixture",
        audio=AudioConfig(cache_dir=tmp_path / "cache"),
    )
    monkeypatch.setattr(server_module, "_config", config)
    save_cached(
        SongAnalysis(
            file_path=str(click_track),
            file_name=click_track.name,
            duration_seconds=3.0,
            beats=BeatMap(tempo=120.0, beat_times=[0.0, 0.5, 1.0, 1.5], downbeat_times=[0.0]),
        ),
        click_track,
        config.audio.cache_dir,
    )
    return folder


async def _call(args: dict) -> dict:
    async with create_connected_server_and_client_session(server_module.mcp) as client:
        result = await client.call_tool("write_sequence", args)
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


async def test_writes_a_plan_into_the_active_show(show, click_track):
    report = await _call({"mp3_path": str(click_track), "plan": PLAN, "timing_tracks": ["Beats"]})

    assert report["written"] is True and report["errors"] == []
    assert Path(report["path"]) == show / f"{click_track.stem}.xsq"


async def test_plan_path_resolves_against_the_show_folder(show, click_track):
    (show / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")

    report = await _call({"mp3_path": str(click_track), "plan_path": "plan.json", "validate_only": True})

    assert report["errors"] == [] and report["effects"] == 1


async def test_a_plan_file_with_a_bom_is_read(show, click_track):
    (show / "bom.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(PLAN).encode("utf-8"))

    report = await _call({"mp3_path": str(click_track), "plan_path": "bom.json", "validate_only": True})

    assert report["errors"] == [] and report["effects"] == 1


@pytest.mark.parametrize("args", [{}, {"plan": PLAN, "plan_path": "plan.json"}])
async def test_exactly_one_plan_source_is_required(show, click_track, args):
    payload = await _call({"mp3_path": str(click_track), **args})

    assert "exactly one" in payload["error"]


async def test_an_unreadable_plan_file_is_an_error(show, click_track):
    (show / "bad.json").write_text("{not json", encoding="utf-8")

    payload = await _call({"mp3_path": str(click_track), "plan_path": "bad.json"})

    assert "bad.json" in payload["error"]


async def test_a_plan_file_must_hold_a_list(show, click_track):
    (show / "obj.json").write_text("{}", encoding="utf-8")

    payload = await _call({"mp3_path": str(click_track), "plan_path": "obj.json"})

    assert "list" in payload["error"]


async def test_a_missing_song_is_an_error(show, tmp_path):
    payload = await _call({"mp3_path": str(tmp_path / "missing.mp3"), "plan": PLAN})

    assert "not found" in payload["error"]
