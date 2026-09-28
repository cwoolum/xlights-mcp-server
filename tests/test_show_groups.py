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
    assert rows.submodel_count == 2
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

    assert group.leaf_models == [] and group.child_groups == [] and group.has_submodels is False and group.submodel_count == 0


def test_everything_flat_excludes_placeholder():
    groups = _groups()

    assert "Spare - Dont Map" not in groups["Everything Flat"].leaf_models


def test_roof_edges_parent_groups():
    groups = _groups()

    assert groups["Roof Edges"].parent_groups == ["House"]


def test_normal_group_has_no_submodels():
    groups = _groups()

    assert groups["Lanterns"].has_submodels is False
    assert groups["Lanterns"].submodel_count == 0


def test_submodel_count_counts_only_submodel_members(tmp_path):
    show = _show_with_extra(
        tmp_path, extra_group='<modelGroup name="Mixed" models="Pipe 1,Pipe 2,Pipe 3,Pipe 4/Top"/>'
    )

    mixed = _groups_for(show)["Mixed"]

    assert mixed.has_submodels is True
    assert mixed.submodel_count == 1


def _show_with_extra(tmp_path: Path, extra_model: str = "", extra_group: str = "") -> Path:
    """Copy the fixture show into tmp_path, optionally adding a model/group."""
    xml = (SHOW / "xlights_rgbeffects.xml").read_text()
    if extra_model:
        xml = xml.replace(
            '<modelGroup name="Legacy Arches"',
            f'{extra_model}\n    <modelGroup name="Legacy Arches"',
        )
    if extra_group:
        xml = xml.replace("</modelGroups>", f"    {extra_group}\n  </modelGroups>")
    show_dir = tmp_path / "show"
    show_dir.mkdir()
    (show_dir / "xlights_rgbeffects.xml").write_text(xml)
    return show_dir


def test_model_name_with_slash_counts_as_model_not_submodel(tmp_path):
    show = _show_with_extra(
        tmp_path,
        extra_model='<model name="AC/DC Sign" DisplayAs="Single Line" WorldPosY="50.0"/>',
        extra_group='<modelGroup name="Signs" models="AC/DC Sign,Lantern1"/>',
    )

    signs = _groups_for(show)["Signs"]

    assert signs.leaf_models == ["AC/DC Sign", "Lantern1"]
    assert signs.has_submodels is False


def test_unknown_member_warns(tmp_path):
    show = _show_with_extra(
        tmp_path, extra_group='<modelGroup name="Bogus" models="Not A Real Thing"/>'
    )

    warnings = load_show_config(show).warnings

    assert any("'Bogus'" in w and "unknown member 'Not A Real Thing'" in w for w in warnings)


def test_group_name_whitespace_is_stripped(tmp_path):
    show = _show_with_extra(tmp_path, extra_group='<modelGroup name="  Spacey  " models="Lantern1"/>')

    assert "Spacey" in _groups_for(show)


def test_non_finite_world_pos_y_is_none(tmp_path):
    show = _show_with_extra(
        tmp_path, extra_model='<model name="Nan Model" DisplayAs="Single Line" WorldPosY="nan"/>'
    )

    models = {m.name: m for m in load_show_models(show)}

    assert models["Nan Model"].world_pos_y is None


def _groups_for(show_path: Path):
    return {g.name: g for g in load_show_config(show_path).model_groups}
