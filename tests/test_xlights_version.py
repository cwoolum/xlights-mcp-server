"""installed_xlights_version: registry first, then the show folder's sequences, then the default."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from xlights_mcp.xlights import version
from xlights_mcp.xlights.version import installed_xlights_version
from xlights_mcp.xlights.xsq_writer import DEFAULT_XLIGHTS_VERSION


@pytest.fixture(autouse=True)
def _fresh_registry_cache():
    version._registry_version.cache_clear()
    yield
    version._registry_version.cache_clear()


def _sequence(folder: Path, name: str, xlights_version: str) -> None:
    (folder / name).write_text(
        f'<?xml version="1.0"?><xsequence><head><version>{xlights_version}</version></head></xsequence>',
        encoding="utf-8",
    )


def test_the_registry_version_wins_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    entries = [("Other Tool", "9.9"), ("xLights version 2026.17", "2026.17")]
    monkeypatch.setattr(version, "_read_uninstall_entries", lambda: entries)
    _sequence(tmp_path, "a.xsq", "2030.1")

    assert installed_xlights_version(tmp_path) == "2026.17"


def test_the_newest_matching_registry_entry_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    entries = [("xLights version 2025.9", "2025.9"), ("xLights version 2026.17", "2026.17"), ("xLights", "2026.5")]
    monkeypatch.setattr(version, "_read_uninstall_entries", lambda: entries)

    assert installed_xlights_version(tmp_path) == "2026.17"


def test_the_version_is_returned_as_written(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    _sequence(tmp_path, "a.xsq", "2026.05")
    _sequence(tmp_path, "b.xsq", "2025.13")

    assert installed_xlights_version(tmp_path) == "2026.05"


def test_the_show_folder_supplies_the_highest_version_off_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    _sequence(tmp_path, "a.xsq", "2024.19")
    _sequence(tmp_path, "b.xsq", "2025.9")
    _sequence(tmp_path, "c.xsq", "2025.13")

    assert installed_xlights_version(tmp_path) == "2025.13"


def test_versions_compare_as_integers_not_text(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    _sequence(tmp_path, "a.xsq", "2025.9")
    _sequence(tmp_path, "b.xsq", "2025.10")

    assert installed_xlights_version(tmp_path) == "2025.10"


def test_a_registry_without_xlights_falls_back_to_the_show_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(version, "_read_uninstall_entries", lambda: [("Other Tool", "9.9")])
    _sequence(tmp_path, "a.xsq", "2025.11")

    assert installed_xlights_version(tmp_path) == "2025.11"


def test_a_failing_registry_falls_back_without_raising(tmp_path, monkeypatch):
    def broken():
        raise OSError("no registry")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(version, "_read_uninstall_entries", broken)

    assert installed_xlights_version(tmp_path) == DEFAULT_XLIGHTS_VERSION


def test_unreadable_or_versionless_sequences_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    (tmp_path / "bad.xsq").write_bytes(b"\xff\xfe not xml")
    (tmp_path / "none.xsq").write_text("<xsequence/>", encoding="utf-8")
    _sequence(tmp_path, "odd.xsq", "next-year")

    assert installed_xlights_version(tmp_path) == DEFAULT_XLIGHTS_VERSION


def test_no_show_folder_gives_the_default(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert installed_xlights_version() == DEFAULT_XLIGHTS_VERSION
    assert installed_xlights_version(Path("does-not-exist")) == DEFAULT_XLIGHTS_VERSION
