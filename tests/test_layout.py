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
