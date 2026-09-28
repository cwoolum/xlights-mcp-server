"""create_sequence's legacy engine groups models by feature-tier groups."""

from __future__ import annotations

from pathlib import Path

from xlights_mcp.sequencer.engine import _detect_model_groups
from xlights_mcp.xlights.show import load_show_config

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


def test_engine_groups_are_the_feature_tier_groups():
    show = load_show_config(SHOW)

    groups, ungrouped, _ = _detect_model_groups(show.models, show)

    assert set(groups) == {"Roof Edges", "Door", "Pipes", "Lanterns", "Legacy Arches"}
    assert [m.name for m in groups["Roof Edges"]] == ["Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert {m.name for m in ungrouped} == {"Tree 6ft", "Roof Mid - Null - Do Not Map", "Spare - Dont Map"}
