"""installed_xlights_version: registry first, then the show folder's sequences, then the default."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from xlights_mcp.xlights import version
from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.version import installed_xlights_version
from xlights_mcp.xlights.xsq_writer import DEFAULT_XLIGHTS_VERSION, SequenceSpec, write_xsq


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def install(registry_versions):
        reader = registry_versions if callable(registry_versions) else lambda: registry_versions
        monkeypatch.setattr(version, "_registry_versions", reader)

    return install


def _sequence(folder: Path, name: str, xlights_version: str) -> None:
    (folder / name).write_text(
        f'<?xml version="1.0"?><xsequence><head><version>{xlights_version}</version></head></xsequence>',
        encoding="utf-8",
    )


def test_the_registry_version_wins_on_windows(tmp_path, windows):
    windows(["2026.17"])
    _sequence(tmp_path, "a.xsq", "2030.1")

    assert installed_xlights_version(tmp_path) == "2026.17"


def test_the_newest_registry_entry_wins(tmp_path, windows):
    windows(["2025.9", "2026.17", "2026.5"])

    assert installed_xlights_version(tmp_path) == "2026.17"


def test_junk_registry_versions_are_ignored(tmp_path, windows):
    windows(["", "next", "2026.5"])

    assert installed_xlights_version(tmp_path) == "2026.5"


def test_the_version_is_returned_as_written(tmp_path, linux):
    _sequence(tmp_path, "a.xsq", "2026.05")
    _sequence(tmp_path, "b.xsq", "2025.13")

    assert installed_xlights_version(tmp_path) == "2026.05"


def test_the_show_folder_supplies_the_highest_version_off_windows(tmp_path, linux):
    _sequence(tmp_path, "a.xsq", "2024.19")
    _sequence(tmp_path, "b.xsq", "2025.9")
    _sequence(tmp_path, "c.xsq", "2025.13")

    assert installed_xlights_version(tmp_path) == "2025.13"


def test_versions_compare_as_integers_not_text(tmp_path, linux):
    _sequence(tmp_path, "a.xsq", "2025.9")
    _sequence(tmp_path, "b.xsq", "2025.10")

    assert installed_xlights_version(tmp_path) == "2025.10"


def test_sequences_this_server_generated_do_not_count(tmp_path, linux):
    show = ShowConfig(show_path=str(tmp_path), show_name="t")
    write_xsq(SequenceSpec(duration_ms=1000, xlights_version="2099.1"), show, tmp_path / "generated.xsq")
    _sequence(tmp_path, "hand.xsq", "2025.13")

    assert installed_xlights_version(tmp_path) == "2025.13"


def test_a_registry_without_xlights_falls_back_to_the_show_folder(tmp_path, windows):
    windows([])
    _sequence(tmp_path, "a.xsq", "2025.11")

    assert installed_xlights_version(tmp_path) == "2025.11"


def test_a_failing_registry_falls_back_without_raising(tmp_path, windows):
    def broken():
        raise OSError("no registry")

    windows(broken)

    assert installed_xlights_version(tmp_path) == DEFAULT_XLIGHTS_VERSION


def test_unreadable_or_versionless_sequences_are_skipped(tmp_path, linux):
    (tmp_path / "bad.xsq").write_bytes(b"\xff\xfe not xml")
    (tmp_path / "none.xsq").write_text("<xsequence/>", encoding="utf-8")
    (tmp_path / "folder.xsq").mkdir()
    _sequence(tmp_path, "odd.xsq", "next-year")

    assert installed_xlights_version(tmp_path) == DEFAULT_XLIGHTS_VERSION


@pytest.mark.usefixtures("linux")
def test_no_show_folder_gives_the_default():
    assert installed_xlights_version() == DEFAULT_XLIGHTS_VERSION
    assert installed_xlights_version(Path("does-not-exist")) == DEFAULT_XLIGHTS_VERSION
