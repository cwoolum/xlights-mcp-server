"""Telling generated sequences from hand-made ones, and list_sequences' view of it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from show_fixtures import call_tool

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig
from xlights_mcp.xlights import xsq_reader
from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.xsq_reader import is_generated_file, latest_hand_made_sequence
from xlights_mcp.xlights.xsq_writer import SequenceSpec, write_xsq

HAND_MADE = "<xsequence><head><comment></comment></head><ElementEffects/></xsequence>"


def _generated(path: Path) -> Path:
    write_xsq(SequenceSpec(duration_ms=1000), ShowConfig(show_path=str(path.parent), show_name="t"), path)
    return path


def _hand_made(path: Path, mtime: float | None = None) -> Path:
    path.write_text(HAND_MADE, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_is_generated_file(tmp_path):
    assert is_generated_file(_generated(tmp_path / "gen.xsq"))
    assert not is_generated_file(_hand_made(tmp_path / "hand.xsq"))


def test_latest_hand_made_sequence_skips_generated_files(tmp_path):
    _hand_made(tmp_path / "Old.xsq", mtime=1_000_000)
    newest = _hand_made(tmp_path / "New.xsq", mtime=2_000_000)
    gen = _generated(tmp_path / "Gen.xsq")
    os.utime(gen, (3_000_000, 3_000_000))

    assert latest_hand_made_sequence(tmp_path) == newest


def _typed(path: Path, sequence_type: str, mtime: float) -> Path:
    path.write_text(
        f"<xsequence><head><sequenceType>{sequence_type}</sequenceType></head><ElementEffects/></xsequence>",
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


def test_latest_hand_made_sequence_prefers_a_song_over_a_newer_animation(tmp_path):
    song = _typed(tmp_path / "Song.xsq", "Media", mtime=1_000_000)
    _typed(tmp_path / "Standby.xsq", "Animation", mtime=2_000_000)

    assert latest_hand_made_sequence(tmp_path) == song


def test_latest_hand_made_sequence_falls_back_to_the_newest_animation(tmp_path):
    _typed(tmp_path / "Old.xsq", "Animation", mtime=1_000_000)
    newest = _typed(tmp_path / "New.xsq", "Animation", mtime=2_000_000)

    assert latest_hand_made_sequence(tmp_path) == newest


def test_latest_hand_made_sequence_ignores_a_newer_generated_song(tmp_path):
    animation = _typed(tmp_path / "Standby.xsq", "Animation", mtime=1_000_000)
    generated = _generated(tmp_path / "Gen.xsq")
    os.utime(generated, (2_000_000, 2_000_000))
    assert b"<sequenceType>Media</sequenceType>" in generated.read_bytes()

    assert latest_hand_made_sequence(tmp_path) == animation


def test_latest_hand_made_sequence_is_none_without_one(tmp_path):
    _generated(tmp_path / "Gen.xsq")

    assert latest_hand_made_sequence(tmp_path) is None


@pytest.fixture
def active_show(show_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        server_module, "_config", ServerConfig(show_folders={"fixture": str(show_copy)}, active_show="fixture")
    )
    return show_copy


async def test_list_sequences_flags_generated_sequences(active_show):
    _generated(active_show / "Gen.xsq")
    _hand_made(active_show / "Hand.xsq")

    payload = await call_tool("list_sequences", {})

    flags = {s["name"]: s["generated"] for s in payload["sequences"]}
    assert flags == {"Gen": True, "Hand": False}
    assert all(s["modified"] for s in payload["sequences"])


@pytest.mark.parametrize("stem", ["Hand", "Mr. Sandman"])
async def test_inspect_sequence_accepts_a_name_with_or_without_the_extension(active_show, stem):
    _hand_made(active_show / f"{stem}.xsq")

    by_name = await call_tool("inspect_sequence", {"sequence_name": stem})
    by_file = await call_tool("inspect_sequence", {"sequence_name": f"{stem}.xsq"})

    assert by_name["file_name"] == by_file["file_name"] == f"{stem}.xsq"


def test_latest_hand_made_sequence_ignores_directories_and_unreadable_files(tmp_path, monkeypatch):
    (tmp_path / "Folder.xsq").mkdir()
    readable = _hand_made(tmp_path / "Readable.xsq", mtime=1_000_000)
    _hand_made(tmp_path / "Locked.xsq", mtime=2_000_000)
    real = xsq_reader.is_generated_file

    def flaky(path):
        if path.name == "Locked.xsq":
            raise PermissionError(path)
        return real(path)

    monkeypatch.setattr(xsq_reader, "is_generated_file", flaky)

    assert latest_hand_made_sequence(tmp_path) == readable


async def test_list_sequences_skips_directories_and_marks_unreadable_files(active_show, monkeypatch):
    (active_show / "Folder.xsq").mkdir()
    _hand_made(active_show / "Hand.xsq")
    _hand_made(active_show / "Locked.xsq")
    real = xsq_reader.is_generated_file

    def flaky(path):
        if path.name == "Locked.xsq":
            raise PermissionError(path)
        return real(path)

    monkeypatch.setattr(xsq_reader, "is_generated_file", flaky)

    payload = await call_tool("list_sequences", {})

    flags = {s["name"]: s["generated"] for s in payload["sequences"]}
    assert flags == {"Hand": False, "Locked": None}


@pytest.mark.parametrize("name", ["", "  "])
async def test_inspect_sequence_needs_a_name(active_show, name):
    assert await call_tool("inspect_sequence", {"sequence_name": name}) == {"error": "sequence name is required"}
