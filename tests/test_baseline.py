"""The create_sequence baseline plan on the fixture show."""

from __future__ import annotations

import numpy as np
import pytest
from show_fixtures import SHOW_GROUPS, make_analysis

from xlights_mcp.audio.sections import SongSection
from xlights_mcp.sequencer.engine import (
    ACCENT_MS,
    BED_EFFECTS,
    FACE_BED_KEYS,
    MOTION_EFFECTS,
    WASH_BRIGHTNESS,
    _effect_name_from_key,
    _face_placements,
    build_baseline_plan,
)
from xlights_mcp.sequencer.plan import validate_plan
from xlights_mcp.xlights.effects import XLIGHTS_EFFECT_NAMES
from xlights_mcp.xlights.show import load_show_config

SHOW = load_show_config(SHOW_GROUPS)
COLORS = ["#FF6600", "#800080"]
SECTIONS = [
    ("intro", 0, 8, 0.2), ("verse", 8, 20, 0.5), ("chorus", 20, 32, 0.8),
    ("breakdown", 32, 40, 0.3), ("drop", 40, 52, 0.9), ("outro", 52, 60, 0.2),
]
ANALYSIS = make_analysis(
    60.0,
    np.arange(0, 60, 0.5).tolist(),
    np.arange(0, 60, 2.0).tolist(),
    sections=[SongSection(label=l, start_time=s, end_time=e, energy_level=en) for l, s, e, en in SECTIONS],
)
FEATURES = {"Door", "Lanterns", "Legacy Arches", "Pipes", "Roof Edges"}
ACCENT_PROPS = {
    "Door L", "Door R", "Lantern1", "Lantern2", "Lantern3", "Arch 1", "Arch 2",
    "Roof Left", "Roof Right", "Under Left", "Under Right",
}


def _plan(exclude=frozenset()):
    return build_baseline_plan(ANALYSIS, SHOW, COLORS, exclude)


def _within(plan, start_s, end_s, layer=None):
    return [
        p for p in plan
        if start_s * 1000 <= p["start_ms"] < end_s * 1000 and (layer is None or p["layer"] == layer)
    ]


def test_the_plan_passes_the_writer_checks():
    result = validate_plan(_plan(), SHOW, 60000, XLIGHTS_EFFECT_NAMES)

    assert result.errors == []
    assert result.warnings == []


def test_elements_are_wash_or_feature_groups_or_accent_props_on_layers_0_and_1():
    plan = _plan()

    assert {p["element"] for p in plan} <= FEATURES | ACCENT_PROPS | {"Everything Flat"}
    assert {p["layer"] for p in plan} == {0, 1}


def test_quiet_sections_get_only_the_largest_wash_group_dimmed():
    plan = _plan()

    for start, end in [(0, 8), (32, 40), (52, 60)]:
        (wash,) = _within(plan, start, end)
        assert (wash["element"], wash["effect"]) == ("Everything Flat", "Color Wash")
        assert (wash["start_ms"], wash["end_ms"]) == (start * 1000, end * 1000)
        assert wash["palette"] == {"colors": COLORS, "brightness": WASH_BRIGHTNESS}


def test_feature_halves_take_turns_by_height():
    plan = _plan()

    lit = [{p["element"] for p in _within(plan, s, e, layer=0)} for s, e in [(8, 20), (20, 32), (40, 52)]]
    assert lit == [{"Pipes", "Legacy Arches", "Door"}, {"Lanterns", "Roof Edges"}, {"Pipes", "Legacy Arches", "Door"}]


def test_accents_hit_each_downbeat_of_accent_sections_on_props_not_already_lit():
    plan = _plan()

    chorus = _within(plan, 20, 32, layer=1)
    assert [p["start_ms"] for p in chorus] == [20000, 22000, 24000, 26000, 28000, 30000]
    assert all(p["effect"] == "On" and p["end_ms"] - p["start_ms"] == ACCENT_MS for p in chorus)
    assert [p["element"] for p in chorus] == ["Door L", "Door R", "Arch 1", "Arch 2", "Door L", "Door R"]
    assert _within(plan, 8, 20, layer=1) == []


def test_every_placement_uses_the_given_colours():
    assert all(p["palette"]["colors"] == COLORS for p in _plan())


def test_groups_holding_excluded_models_are_left_out():
    plan = _plan(exclude=frozenset({"Lantern2"}))

    elements = {p["element"] for p in plan}
    assert not elements & {"Lanterns", "All", "Everything Flat", "Lantern2"}
    assert {p["element"] for p in _within(plan, 0, 8)} == {"House"}


def test_every_table_key_is_a_known_xlights_effect():
    keys = {k for table in (BED_EFFECTS, MOTION_EFFECTS) for ks in table.values() for k in ks}
    keys |= {"ColorWash_slow", "On_solid", "Twinkle_dense", *FACE_BED_KEYS}
    assert {_effect_name_from_key(k) for k in keys} <= XLIGHTS_EFFECT_NAMES


def test_without_a_wash_group_quiet_sections_stay_dark():
    plan = _plan(exclude=frozenset({"Door L", "Lantern2"}))

    assert _within(plan, 0, 8) == []


def _sections(duration_s, downbeats, *sections):
    return make_analysis(
        duration_s, [], downbeats,
        sections=[SongSection(label=l, start_time=s, end_time=e, energy_level=en) for l, s, e, en in sections],
    )


def test_an_unknown_section_label_is_treated_as_features():
    plan = build_baseline_plan(_sections(8.0, [0.0, 2.0, 4.0, 6.0], ("mystery", 0, 8, 0.5)), SHOW, COLORS)

    assert {p["element"] for p in plan} == {"Pipes", "Legacy Arches", "Door"}
    assert {p["layer"] for p in plan} == {0}


@pytest.mark.parametrize("end_s", [4.0, 4.01])
def test_a_section_shorter_than_one_frame_is_skipped(end_s):
    analysis = _sections(8.0, [0.0, 2.0, 4.0, 6.0], ("verse", 0, 4, 0.5), ("chorus", 4.0, end_s, 0.8))

    plan = build_baseline_plan(analysis, SHOW, COLORS)

    assert [p for p in plan if p["start_ms"] >= 4000] == []
    assert validate_plan(plan, SHOW, analysis.duration_ms, XLIGHTS_EFFECT_NAMES).errors == []


def test_a_downbeat_in_the_last_frame_gets_no_accent():
    analysis = _sections(10.01, [0.0, 2.0, 4.0, 6.0, 8.0, 10.0], ("chorus", 0, 10.01, 0.8))

    plan = build_baseline_plan(analysis, SHOW, COLORS)

    assert [p["start_ms"] for p in plan if p["layer"] == 1] == [0, 2000, 4000, 6000, 8000]
    assert validate_plan(plan, SHOW, analysis.duration_ms, XLIGHTS_EFFECT_NAMES).errors == []


LAST_FRAME_SECTION = _sections(10.02, [0.0, 2.0, 4.0, 6.0, 8.0], ("chorus", 0, 9.99, 0.8), ("verse", 9.99, 10.02, 0.5))


def test_a_section_starting_in_the_last_frame_is_skipped():
    plan = build_baseline_plan(LAST_FRAME_SECTION, SHOW, COLORS)

    assert max(p["start_ms"] for p in plan) < 10000
    assert validate_plan(plan, SHOW, LAST_FRAME_SECTION.duration_ms, XLIGHTS_EFFECT_NAMES).errors == []


def test_face_backgrounds_skip_a_section_starting_in_the_last_frame():
    plan = _face_placements(LAST_FRAME_SECTION, "Lantern2", "Singing Face", "Vocals", COLORS)

    assert [(p["effect"], p["start_ms"], p["end_ms"]) for p in plan if p["layer"] == 0] == [("Twinkle", 0, 10000)]
    assert validate_plan(plan, SHOW, LAST_FRAME_SECTION.duration_ms, XLIGHTS_EFFECT_NAMES).errors == []


def test_a_show_without_feature_groups_gets_no_feature_or_accent_placements():
    show = SHOW.model_copy(update={"model_groups": [g for g in SHOW.model_groups if g.name in {"All", "Everything Flat"}]})

    plan = build_baseline_plan(ANALYSIS, show, COLORS)

    assert {(p["element"], p["layer"]) for p in plan} == {("Everything Flat", 0)}
    assert len(plan) == 3
