"""The sequence_song playbook prompt."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig
from xlights_mcp.prompts import render_sequence_song

HUMAN_STYLE = Path(__file__).parent / "fixtures" / "sequences" / "Human Style.xsq"


def test_renders_every_placeholder():
    text = render_sequence_song("C:/music/Song.mp3", None, None)

    assert "C:/music/Song.mp3" in text
    assert not re.search(r"\{\{\w+\}\}", text)


def test_a_reference_is_profiled():
    text = render_sequence_song("Song.mp3", "Human Style.xsq", None)

    assert "profile_sequence" in text and "Human Style.xsq" in text


def test_without_a_reference_it_gives_default_targets():
    text = render_sequence_song("Song.mp3", None, None)

    assert "no hand-made sequence" in text.lower()


def test_show_notes_are_embedded():
    assert "Never light the neighbours' side" in render_sequence_song("Song.mp3", None, "Never light the neighbours' side")


@pytest.fixture
def active_show(show_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        server_module, "_config", ServerConfig(show_folders={"fixture": str(show_copy)}, active_show="fixture")
    )
    return show_copy


async def _get(args: dict) -> str:
    async with create_connected_server_and_client_session(server_module.mcp) as client:
        prompts = await client.list_prompts()
        assert "sequence_song" in {p.name for p in prompts.prompts}
        result = await client.get_prompt("sequence_song", args)
    return result.messages[0].content.text


async def test_prompt_defaults_to_the_latest_hand_made_sequence(active_show):
    shutil.copy(HUMAN_STYLE, active_show)

    text = await _get({"mp3_path": "Song.mp3"})

    assert "Human Style.xsq" in text


async def test_an_explicit_reference_wins(active_show):
    shutil.copy(HUMAN_STYLE, active_show)

    text = await _get({"mp3_path": "Song.mp3", "reference_sequence": "Other.xsq"})

    assert "Other.xsq" in text and "Human Style.xsq" not in text


async def test_show_claude_md_is_embedded(active_show):
    (active_show / ".claude").mkdir()
    (active_show / ".claude" / "CLAUDE.md").write_text("Keep the tombstones white.", encoding="utf-8")

    assert "Keep the tombstones white." in await _get({"mp3_path": "Song.mp3"})
