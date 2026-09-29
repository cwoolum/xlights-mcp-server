"""get_show_layout and list_models through an in-memory MCP session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


@pytest.fixture
def fixture_show(monkeypatch: pytest.MonkeyPatch) -> ServerConfig:
    config = ServerConfig(show_folders={"fixture": str(SHOW)}, active_show="fixture")
    monkeypatch.setattr(server_module, "_config", config)
    return config


async def _call(name: str, args: dict) -> dict:
    async with create_connected_server_and_client_session(server_module.mcp) as client:
        result = await client.call_tool(name, args)
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


async def test_get_show_layout_for_the_active_show(fixture_show):
    layout = await _call("get_show_layout", {})

    tiers = {g["name"]: g["tier"] for g in layout["groups"]}
    assert layout["show"] == "fixture"
    assert tiers["House"] == "wash" and tiers["Pipes"] == "feature" and tiers["Pipe Rows"] == "skip"


async def test_get_show_layout_by_name(fixture_show):
    layout = await _call("get_show_layout", {"show_name": "fixture"})

    assert layout["show"] == "fixture"


async def test_get_show_layout_unknown_show(fixture_show):
    payload = await _call("get_show_layout", {"show_name": "nope"})

    assert "error" in payload


async def test_list_models_hides_placeholders_by_default(fixture_show):
    default = await _call("list_models", {})
    everything = await _call("list_models", {"include_placeholders": True})

    names = {m["name"] for m in default["models"]}
    assert "Spare - Dont Map" not in names and "Roof Left" in names
    assert default["model_count"] == 26
    assert everything["model_count"] == 28
