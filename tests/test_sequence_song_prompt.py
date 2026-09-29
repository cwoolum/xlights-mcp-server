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
DEFAULT_TEXT = render_sequence_song("Song.mp3", None, None)


def test_renders_every_placeholder():
    text = render_sequence_song("C:/music/Song.mp3", None, None)

    assert "C:/music/Song.mp3" in text
    assert not re.search(r"\{\{\w+\}\}", text)


def test_a_reference_is_profiled():
    text = render_sequence_song("Song.mp3", "Human Style.xsq", None)

    assert "profile_sequence" in text and "Human Style.xsq" in text


def test_without_a_reference_it_gives_default_targets():
    assert "no hand-made sequence" in DEFAULT_TEXT.lower()


def test_an_existing_sequence_gets_a_new_name_unless_the_user_agreed_to_replace_it():
    assert "pass a new `name`, or `overwrite: true` only if the user agreed" in DEFAULT_TEXT


def test_accents_follow_drum_onsets():
    assert "drum onsets" in DEFAULT_TEXT


def test_dropouts_come_from_silences_and_hits_from_kicks():
    assert '`get_stem_events(stem=..., kind="silences")`' in DEFAULT_TEXT
    assert '`get_stem_events(stem="drums", kind="kicks")`' in DEFAULT_TEXT
    assert "`merge_gap_ms`" in DEFAULT_TEXT


def test_the_kicks_timing_track_is_requested_when_stems_are_available():
    assert 'timing_tracks: ["Beats", "Bars"]`. Add `"Kicks"`' in DEFAULT_TEXT


def test_show_notes_are_embedded():
    assert "Never light the neighbours' side" in render_sequence_song("Song.mp3", None, "Never light the neighbours' side")


def test_show_notes_are_quoted_so_their_headings_dont_clash_with_the_playbook():
    text = render_sequence_song("Song.mp3", None, "## Rules\n\nNo strobes.\n\n\n# Tips\nKeep it warm.")

    assert "> ## Rules\n>\n> No strobes.\n>\n>\n> # Tips\n> Keep it warm.\n" in text
    assert "\n## Rules" not in text and "\n# Tips" not in text


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


async def test_an_empty_reference_falls_back_to_the_default(active_show):
    shutil.copy(HUMAN_STYLE, active_show)

    text = await _get({"mp3_path": "Song.mp3", "reference_sequence": ""})

    assert "Human Style.xsq" in text


async def test_without_an_active_show_it_renders_the_no_reference_text(monkeypatch):
    monkeypatch.setattr(server_module, "_config", ServerConfig())

    text = await _get({"mp3_path": "Song.mp3"})

    assert "no hand-made sequence" in text.lower()


@pytest.mark.parametrize("make_notes", [
    lambda p: p.write_bytes(b"\xff\xfe\x00bad"),
    lambda p: p.mkdir(),
], ids=["invalid-bytes", "directory"])
async def test_unreadable_show_notes_are_left_out(active_show, make_notes):
    (active_show / ".claude").mkdir()
    make_notes(active_show / ".claude" / "CLAUDE.md")

    text = await _get({"mp3_path": "Song.mp3"})

    assert "Show notes" not in text and "Sequence Song.mp3" in text


def test_layer_zero_is_said_to_draw_on_top():
    assert "Layer 0 is drawn on top" in DEFAULT_TEXT
    assert "bases (wash, Plasma, solid colour) on the highest layer" in DEFAULT_TEXT
    assert "most elements need only layer 0" not in DEFAULT_TEXT


def test_blend_modes_are_explained():
    assert '`"blend"`' in DEFAULT_TEXT
    assert all(f"`{mode}`" in DEFAULT_TEXT for mode in ("Additive", "1 reveals 2", "Max", "Layered"))


def test_value_curves_are_explained_in_real_units():
    assert "E_VALUECURVE_<setting>" in DEFAULT_TEXT and "RV=TRUE" in DEFAULT_TEXT
    assert "C_VALUECURVE_Brightness=Active=TRUE|Id=ID_VALUECURVE_Brightness|Type=Ramp" in DEFAULT_TEXT
    assert "not percentages" in DEFAULT_TEXT
    assert "check the ramp in xLights the first time" in DEFAULT_TEXT


def test_value_curve_strings_are_only_copied_from_current_version_sequences():
    assert "Copy working strings only from sequences saved in the current xLights version" in DEFAULT_TEXT
    assert "`inspect_sequence` shows a sequence's `version`" in DEFAULT_TEXT
    assert "check Min and Max against the units above" in DEFAULT_TEXT


def test_music_sparkles_are_offered_on_palettes():
    assert "`music_sparkles: true` (with `sparkles` above 0)" in DEFAULT_TEXT
