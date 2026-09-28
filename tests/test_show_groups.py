"""Show parsing: placeholders, model height, model groups."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.xlights.models import ModelGroup, is_placeholder_name
from xlights_mcp.xlights.show import load_model_groups, load_show_config, load_show_models

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Tier 1 Mid - Null 1-2 - Dont Map", True),
        ("Spare - Don't Map", True),
        ("Tier 1 Roof Left - Null - Do Not Map", True),
        ("DONT MAP", True),
        ("Donut Mapper", False),
        ("Roof Left", False),
    ],
)
def test_placeholder_names(name, expected):
    assert is_placeholder_name(name) is expected


def test_models_carry_height_and_placeholder_flag():
    models = {m.name: m for m in load_show_models(SHOW)}

    assert models["Roof Left"].world_pos_y == 150.0
    assert models["Spare - Dont Map"].world_pos_y is None
    assert models["Spare - Dont Map"].is_placeholder is True
    assert models["Roof Left"].is_placeholder is False


def _groups():
    return {g.name: g for g in load_show_config(SHOW).model_groups}


def test_groups_come_from_modelgroups_and_the_legacy_models_section():
    groups = _groups()

    assert "All" in groups and "Legacy Arches" in groups
    assert len(groups) == 16  # 17 definitions, one duplicate


def test_duplicate_group_name_keeps_first_definition_and_warns():
    show = load_show_config(SHOW)
    door = next(g for g in show.model_groups if g.name == "Door")

    assert door.members == ["Door L", "Door R"]
    assert any("'Door'" in w and "more than once" in w for w in show.warnings)


def test_nested_groups_resolve_to_real_leaf_models():
    groups = _groups()

    assert groups["Roof Edges"].leaf_models == ["Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert groups["House"].leaf_models == ["Door L", "Door R", "Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert groups["Empty"].leaf_models == []


def test_child_and_parent_groups():
    groups = _groups()

    assert groups["Roof Edges"].child_groups == ["Under Roof"]
    assert groups["Under Roof"].parent_groups == ["Roof Edges"]
    assert groups["House"].parent_groups == ["All"]


def test_submodel_members_map_to_their_parent_model():
    rows = _groups()["Pipe Rows"]

    assert rows.has_submodels is True
    assert rows.leaf_models == ["Pipe 1", "Pipe 2"]


def test_group_cycles_terminate():
    groups = _groups()

    assert groups["Cycle A"].leaf_models == ["Door L"]
    assert groups["Cycle B"].leaf_models == ["Door L"]


def test_load_model_groups_returns_resolved_groups():
    groups = {g.name: g for g in load_model_groups(SHOW)}

    assert groups["House"].child_groups == ["Roof Edges", "Door"]


def test_model_group_still_constructs_with_name_and_members_only():
    group = ModelGroup(name="All Arches", members=["Arch 1"])

    assert group.leaf_models == [] and group.child_groups == [] and group.has_submodels is False
