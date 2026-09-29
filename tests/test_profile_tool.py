"""profile_sequence through an in-memory MCP session."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from show_fixtures import call_tool

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig

HUMAN_STYLE = Path(__file__).parent / "fixtures" / "sequences" / "Human Style.xsq"


@pytest.fixture
def active_show(show_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copy(HUMAN_STYLE, show_copy)
    monkeypatch.setattr(
        server_module, "_config", ServerConfig(show_folders={"fixture": str(show_copy)}, active_show="fixture")
    )
    return show_copy


@pytest.mark.parametrize("xsq_path", ["Human Style", "Human Style.xsq"])
async def test_profiles_a_sequence_in_the_show_folder(active_show, xsq_path):
    profile = await call_tool("profile_sequence", {"xsq_path": xsq_path})

    assert profile["file"] == "Human Style.xsq"
    assert profile["lit_at_once"]["median"] == 2


async def test_accepts_an_absolute_path(active_show):
    profile = await call_tool("profile_sequence", {"xsq_path": str(HUMAN_STYLE)})

    assert profile["total_effects"] == 9


async def test_a_missing_sequence_is_an_error(active_show):
    assert "not found" in (await call_tool("profile_sequence", {"xsq_path": "Nope"}))["error"]


async def test_an_unparseable_sequence_is_an_error(active_show):
    (active_show / "Broken.xsq").write_text("<xsequence>", encoding="utf-8")

    assert "Broken.xsq" in (await call_tool("profile_sequence", {"xsq_path": "Broken"}))["error"]
