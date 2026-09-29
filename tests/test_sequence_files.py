"""Telling generated sequences from hand-made ones, and list_sequences' view of it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from show_fixtures import call_tool

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig
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


async def test_inspect_sequence_accepts_a_name_with_or_without_the_extension(active_show):
    _hand_made(active_show / "Hand.xsq")

    by_name = await call_tool("inspect_sequence", {"sequence_name": "Hand"})
    by_file = await call_tool("inspect_sequence", {"sequence_name": "Hand.xsq"})

    assert by_name["file_name"] == by_file["file_name"] == "Hand.xsq"
