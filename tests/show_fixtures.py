"""Shared builders for show, analysis and MCP-tool tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap

SHOW_GROUPS = Path(__file__).parent / "fixtures" / "show_groups"


def make_analysis(
    duration_s: float,
    beat_times: Sequence[float],
    downbeat_times: Sequence[float],
    path: str | Path = "Song.mp3",
    **fields,
) -> SongAnalysis:
    """A 120 BPM analysis of `path` with the given beat grid."""
    return SongAnalysis(
        file_path=str(path),
        file_name=Path(path).name,
        duration_seconds=duration_s,
        beats=BeatMap(tempo=120.0, beat_times=list(beat_times), downbeat_times=list(downbeat_times)),
        **fields,
    )


async def call_tool(name: str, args: dict) -> dict:
    async with create_connected_server_and_client_session(server_module.mcp) as client:
        result = await client.call_tool(name, args)
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


def write_xsq_stub(path: Path, body: str) -> None:
    """A minimal .xsq holding `body` inside <ElementEffects>."""
    path.write_text(f"<xsequence><ElementEffects>{body}</ElementEffects></xsequence>", encoding="utf-8")
