"""Group tiers and the get_show_layout payload."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from xlights_mcp.xlights.layout import build_show_layout, classify_groups, load_tier_overrides
from xlights_mcp.xlights.show import load_show_config

SHOW = Path(__file__).parent / "fixtures" / "show_groups"

EXPECTED = {
    "All": "wash",
    "House": "wash",
    "Everything Flat": "wash",
    "Roof Edges": "feature",
    "Door": "feature",
    "Pipes": "feature",
    "Lanterns": "feature",
    "Legacy Arches": "feature",
    "Under Roof": "skip",
    "Pipes-Odd": "skip",
    "Pipe Rows": "skip",
    "Empty": "skip",
    "PreviewONLY All": "skip",
    "Single": "skip",
    "Cycle A": "skip",
    "Cycle B": "skip",
}


def test_every_group_gets_the_expected_tier():
    tiers = classify_groups(load_show_config(SHOW))

    assert {name: tier for name, (tier, _) in tiers.items()} == EXPECTED


def test_reasons_explain_the_rule():
    tiers = classify_groups(load_show_config(SHOW))

    assert tiers["Empty"][1] == "empty"
    assert tiers["PreviewONLY All"][1] == "preview-only"
    assert tiers["Pipe Rows"][1] == "submodel group"
    assert tiers["Single"][1] == "single prop"
    assert tiers["Under Roof"][1] == "part of Roof Edges"
    assert tiers["Pipes-Odd"][1] == "part of Pipes"
    assert tiers["Roof Edges"][1] == "top-level, 4 props"
    assert tiers["House"][1] == "2 child groups, 23% of display"
    assert tiers["Everything Flat"][1] == "0 child groups, 96% of display"


def test_large_group_without_child_groups_stays_a_feature():
    # Pipes holds 14 of 26 props but has no child groups, like the Halloween show's Pipes.
    tiers = classify_groups(load_show_config(SHOW))

    assert tiers["Pipes"] == ("feature", "top-level, 14 props")


def test_override_wins():
    tiers = classify_groups(load_show_config(SHOW), overrides={"Pipes-Odd": "feature", "All": "skip"})

    assert tiers["Pipes-Odd"] == ("feature", "override")
    assert tiers["All"] == ("skip", "override")


def _show_copy(tmp_path: Path, overrides: object | None = None, raw: str | None = None) -> Path:
    show = tmp_path / "show"
    show.mkdir()
    shutil.copy(SHOW / "xlights_rgbeffects.xml", show / "xlights_rgbeffects.xml")
    if raw is not None:
        (show / "xlights-mcp.json").write_text(raw, encoding="utf-8")
    elif overrides is not None:
        (show / "xlights-mcp.json").write_text(json.dumps(overrides), encoding="utf-8")
    return show


def test_no_override_file_means_no_overrides(tmp_path):
    assert load_tier_overrides(_show_copy(tmp_path)) == ({}, [])


def test_override_file_invalid_tier_is_ignored_with_warning(tmp_path):
    show = _show_copy(tmp_path, {"tiers": {"Pipes-Odd": "feature", "Door": "sparkly"}})

    overrides, warnings = load_tier_overrides(show)

    assert overrides == {"Pipes-Odd": "feature"}
    assert any("'Door'" in w and "sparkly" in w for w in warnings)


def test_override_file_bad_json_warns(tmp_path):
    overrides, warnings = load_tier_overrides(_show_copy(tmp_path, raw="{not json"))

    assert overrides == {}
    assert warnings and "xlights-mcp.json" in warnings[0]


def test_layout_payload(tmp_path):
    show = _show_copy(tmp_path, {"tiers": {"Pipes-Odd": "feature", "Nope": "skip"}})

    layout = build_show_layout(load_show_config(show), show)
    groups = {g["name"]: g for g in layout["groups"]}

    assert layout["model_count"] == 26
    assert layout["placeholder_count"] == 2
    assert layout["ungrouped_models"] == ["Tree 6ft"]
    assert [g["tier"] for g in layout["groups"]] == sorted(
        (g["tier"] for g in layout["groups"]), key=["wash", "feature", "skip"].index
    )
    assert groups["Pipes-Odd"]["tier"] == "feature"
    assert groups["Roof Edges"]["accent_props"] == ["Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert groups["Pipes"]["accent_props"] == []
    assert groups["Under Roof"]["accent_props"] == []
    assert groups["Roof Edges"]["y_range"] == [120.0, 150.0]
    assert groups["Roof Edges"]["prop_count"] == 4
    assert groups["Roof Edges"]["parent_groups"] == ["House"]
    assert groups["Empty"]["y_range"] is None
    assert any("'Nope'" in w for w in layout["warnings"])
    assert any("'Door'" in w and "more than once" in w for w in layout["warnings"])


def _fixture_with_groups(tmp_path: Path, extra_groups: str) -> Path:
    show = _show_copy(tmp_path)
    xml = show / "xlights_rgbeffects.xml"
    text = xml.read_text(encoding="utf-8")
    xml.write_text(text.replace("</modelGroups>", f"{extra_groups}\n  </modelGroups>"), encoding="utf-8")
    return show


def test_overriding_a_group_to_feature_keeps_its_sub_parts_skipped():
    tiers = classify_groups(load_show_config(SHOW), overrides={"Pipes": "feature"})

    assert tiers["Pipes"] == ("feature", "override")
    assert tiers["Pipes-Odd"] == ("skip", "part of Pipes")


def test_group_with_the_same_props_as_an_earlier_named_feature_is_skipped(tmp_path):
    show = _fixture_with_groups(tmp_path, '<modelGroup name="Door Reverse" models="Door R,Door L"/>')

    tiers = classify_groups(load_show_config(show))

    assert tiers["Door Reverse"] == ("skip", "same props as Door")
    assert tiers["Door"][0] == "feature"


def test_identical_groups_leave_only_the_first_by_name_as_feature(tmp_path):
    show = _fixture_with_groups(
        tmp_path,
        '<modelGroup name="zeta" models="Door L,Door R"/>'
        '<modelGroup name="Alpha" models="Door R,Door L"/>'
        '<modelGroup name="beta" models="Door L,Door R"/>',
    )

    tiers = classify_groups(load_show_config(show))

    assert tiers["Alpha"][0] == "feature"
    assert tiers["beta"] == ("skip", "same props as Alpha")
    assert tiers["zeta"] == ("skip", "same props as Alpha")
    assert tiers["Door"] == ("skip", "same props as Alpha")


def test_smallest_superset_tie_goes_to_the_first_named(tmp_path):
    show = _fixture_with_groups(
        tmp_path,
        '<modelGroup name="Roof Pair Z" models="Roof Left,Roof Right,Under Left"/>'
        '<modelGroup name="Roof Pair A" models="Roof Right,Roof Left,Door L"/>'
        '<modelGroup name="Roof Top" models="Roof Left,Roof Right"/>',
    )

    tiers = classify_groups(load_show_config(show))

    assert tiers["Roof Top"] == ("skip", "part of Roof Pair A")


def test_child_group_missing_from_the_show_does_not_raise():
    show = load_show_config(SHOW)
    show.model_groups[1].child_groups.append("Ghost")

    tiers = classify_groups(show)

    assert tiers["House"][0] == "wash"


def test_override_file_may_start_with_a_utf8_bom(tmp_path):
    show = _show_copy(tmp_path)
    (show / "xlights-mcp.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"tiers": {"Door": "skip"}}).encode())

    assert load_tier_overrides(show) == ({"Door": "skip"}, [])


def test_override_tier_values_are_case_insensitive(tmp_path):
    show = _show_copy(tmp_path, {"tiers": {"Door": "Feature", "Pipes": " SKIP "}})

    overrides, warnings = load_tier_overrides(show)

    assert overrides == {"Door": "feature", "Pipes": "skip"}
    assert warnings == []


def test_non_string_override_tiers_warn_and_are_ignored(tmp_path):
    show = _show_copy(tmp_path, {"tiers": {"Door": 1, "Pipes": None, "Lanterns": "wash"}})

    overrides, warnings = load_tier_overrides(show)

    assert overrides == {"Lanterns": "wash"}
    assert len(warnings) == 2
    assert any("'Door'" in w for w in warnings)
    assert any("'Pipes'" in w for w in warnings)


def test_y_range_is_rounded_and_ignores_non_finite_heights(tmp_path):
    show = _show_copy(tmp_path)
    config = load_show_config(show)
    heights = {"Lantern1": 0.0, "Lantern2": float("nan"), "Lantern3": 90.04}
    for m in config.models:
        if m.name in heights:
            m.world_pos_y = heights[m.name]

    groups = {g["name"]: g for g in build_show_layout(config, show)["groups"]}

    assert groups["Lanterns"]["y_range"] == [0.0, 90.0]


def test_empty_group_overridden_to_feature_warns(tmp_path):
    show = _show_copy(tmp_path, {"tiers": {"Empty": "feature"}})

    layout = build_show_layout(load_show_config(show), show)

    assert any("Empty is overridden to feature but has no props" in w for w in layout["warnings"])
