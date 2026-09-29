"""The xLights version installed on this machine, so written sequences don't trigger a migration."""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

from xlights_mcp.xlights.xsq_writer import DEFAULT_XLIGHTS_VERSION, HEAD_BYTES

_UNINSTALL_ROOTS = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)
_VERSION = re.compile(r"\d+\.\d+")
_HEAD_VERSION = re.compile(r"<version>\s*(\d+\.\d+)\s*</version>")


def installed_xlights_version(show_path: Path | None = None) -> str:
    if sys.platform == "win32":
        found = _registry_version()
        if found:
            return found
    return _show_folder_version(show_path) or DEFAULT_XLIGHTS_VERSION


@lru_cache(maxsize=1)
def _registry_version() -> str | None:
    try:
        entries = _read_uninstall_entries()
    except (OSError, ValueError, ImportError):
        return None
    for name, display_version in entries:
        if name.lower().startswith("xlights") and _VERSION.fullmatch(display_version.strip()):
            return display_version.strip()
    return None


def _read_uninstall_entries() -> list[tuple[str, str]]:
    import winreg

    entries: list[tuple[str, str]] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for root in _UNINSTALL_ROOTS:
            try:
                with winreg.OpenKey(hive, root) as uninstall:
                    for i in range(winreg.QueryInfoKey(uninstall)[0]):
                        entries.extend(_entry(uninstall, winreg.EnumKey(uninstall, i)))
            except OSError:
                continue
    return entries


def _entry(uninstall, subkey: str) -> list[tuple[str, str]]:
    import winreg

    try:
        with winreg.OpenKey(uninstall, subkey) as key:
            name, _ = winreg.QueryValueEx(key, "DisplayName")
            display_version, _ = winreg.QueryValueEx(key, "DisplayVersion")
    except OSError:
        return []
    return [(str(name), str(display_version))]


def _show_folder_version(show_path: Path | None) -> str | None:
    if show_path is None:
        return None
    best: tuple[int, int] | None = None
    try:
        sequences = list(Path(show_path).glob("*.xsq"))
    except OSError:
        return None
    for sequence in sequences:
        try:
            with open(sequence, "rb") as f:
                head = f.read(HEAD_BYTES).decode("utf-8", errors="ignore")
        except OSError:
            continue
        match = _HEAD_VERSION.search(head)
        if match:
            year, _, minor = match.group(1).partition(".")
            candidate = (int(year), int(minor))
            best = max(best, candidate) if best else candidate
    return f"{best[0]}.{best[1]}" if best else None
