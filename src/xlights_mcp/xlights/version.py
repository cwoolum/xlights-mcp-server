"""The xLights version installed on this machine, so written sequences don't trigger a migration."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from xlights_mcp.xlights import xsq_reader
from xlights_mcp.xlights.xsq_writer import DEFAULT_XLIGHTS_VERSION

_UNINSTALL_ROOTS = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)
_VERSION = re.compile(r"\d+\.\d+")


def installed_xlights_version(show_path: Path | None = None) -> str:
    if sys.platform == "win32":
        found = _registry_version()
        if found:
            return found
    return _show_folder_version(show_path) or DEFAULT_XLIGHTS_VERSION


def _sort_key(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _registry_version() -> str | None:
    try:
        versions = _registry_versions()
    except (OSError, ValueError, ImportError):
        return None
    return max((v for v in versions if _VERSION.fullmatch(v)), key=_sort_key, default=None)


def _registry_versions() -> list[str]:
    import winreg

    versions: list[str] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for root in _UNINSTALL_ROOTS:
            try:
                with winreg.OpenKey(hive, root) as uninstall:
                    for i in range(winreg.QueryInfoKey(uninstall)[0]):
                        found = _xlights_display_version(uninstall, winreg.EnumKey(uninstall, i))
                        if found:
                            versions.append(found)
            except OSError:
                continue
    return versions


def _xlights_display_version(uninstall, subkey: str) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(uninstall, subkey) as key:
            name, _ = winreg.QueryValueEx(key, "DisplayName")
            if not str(name).lower().startswith("xlights"):
                return None
            display_version, _ = winreg.QueryValueEx(key, "DisplayVersion")
    except OSError:
        return None
    return str(display_version).strip()


def _hand_made_version(xsq: Path) -> str | None:
    try:
        if xsq_reader.is_generated_file(xsq):
            return None
    except OSError:
        return None
    return xsq_reader.head_version(xsq)


def _show_folder_version(show_path: Path | None) -> str | None:
    if show_path is None:
        return None
    found = (_hand_made_version(xsq) for xsq in show_path.glob("*.xsq"))
    return max((v for v in found if v), key=_sort_key, default=None)
