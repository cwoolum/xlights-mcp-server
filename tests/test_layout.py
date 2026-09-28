"""Group tiers and the get_show_layout payload."""

from __future__ import annotations

from pathlib import Path

from xlights_mcp.xlights.layout import classify_groups
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
