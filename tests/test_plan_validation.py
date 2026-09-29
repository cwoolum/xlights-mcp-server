"""validate_plan: one test per rule in the spec's rule table."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.sequencer.plan import validate_plan
from xlights_mcp.xlights.effects import XLIGHTS_EFFECT_NAMES
from xlights_mcp.xlights.show import load_show_config

SHOW = load_show_config(Path(__file__).parent / "fixtures" / "show_groups")


def _p(**over) -> dict:
    return {"element": "Door", "layer": 0, "effect": "On", "start_ms": 1000, "end_ms": 2000, **over}


def _validate(*placements, duration_ms: int = 20000):
    return validate_plan(list(placements), SHOW, duration_ms, XLIGHTS_EFFECT_NAMES)


def test_a_valid_placement_passes():
    result = _validate(_p())

    assert result.errors == [] and result.warnings == []
    (placement,) = result.placements
    assert (placement.model_name, placement.layer, placement.effect_name) == ("Door", 0, "On")
    assert (placement.start_time_ms, placement.end_time_ms) == (1000, 2000)


def test_models_and_groups_are_both_elements():
    assert _validate(_p(element="Pipes"), _p(element="Tree 6ft")).errors == []


def test_times_round_to_the_frame_grid():
    result = _validate(_p(start_ms=1012, end_ms=1990))

    assert (result.placements[0].start_time_ms, result.placements[0].end_time_ms) == (1000, 2000)
    assert result.adjusted == {"rounded_to_frame": 1, "clipped_to_end": 0}


def test_an_effect_past_the_song_end_is_clipped_to_the_last_frame():
    result = _validate(_p(start_ms=19000, end_ms=25000), duration_ms=20010)

    assert result.placements[0].end_time_ms == 20000
    assert result.adjusted["clipped_to_end"] == 1


@pytest.mark.parametrize("start, end", [(1000, 1010), (2000, 1000)])
def test_an_empty_span_after_rounding_is_an_error(start, end):
    result = _validate(_p(start_ms=start, end_ms=end))

    assert result.placements == []
    assert "ends at or before its start" in result.errors[0]


@pytest.mark.parametrize("start", [20000, 21000])
def test_a_placement_starting_at_or_after_the_song_end_says_so(start):
    result = _validate(_p(start_ms=start, end_ms=22000))

    assert result.placements == []
    assert "starts at or after the song end (last frame 20000 ms)" in result.errors[0]


def test_negative_or_non_numeric_times_are_errors():
    assert "start_ms" in _validate(_p(start_ms=-25)).errors[0]
    assert "end_ms" in _validate(_p(end_ms="2s")).errors[0]
    assert "start_ms" in _validate(_p(start_ms=float("nan"))).errors[0]
    assert "end_ms" in _validate(_p(end_ms=float("inf"))).errors[0]
    assert "start_ms" in _validate(_p(start_ms=True)).errors[0]


def test_errors_name_the_placement():
    assert _validate(_p(element="Nope")).errors[0].startswith("placement 0 ('Nope', layer 0, 1000-2000 ms): ")


def test_overlap_on_the_same_element_and_layer_is_an_error():
    result = _validate(_p(start_ms=0, end_ms=2000), _p(start_ms=1500, end_ms=3000))

    assert result.errors == [
        "placements 0 and 1 overlap on 'Door' layer 0: 0-2000 ms and 1500-3000 ms"
    ]


def test_touching_placements_and_other_layers_do_not_overlap():
    result = _validate(
        _p(start_ms=0, end_ms=2000), _p(start_ms=2000, end_ms=3000), _p(layer=1, start_ms=500, end_ms=2500)
    )

    assert result.errors == []


def test_every_placement_under_a_long_one_is_reported():
    result = _validate(_p(start_ms=0, end_ms=10000), _p(start_ms=1000, end_ms=2000), _p(start_ms=3000, end_ms=4000))

    assert len(result.errors) == 2


@pytest.mark.parametrize("layer", [-1, 3, "1", 1.0, True])
def test_a_layer_outside_0_to_2_is_an_error(layer):
    assert "layer must be an integer 0-2" in _validate(_p(layer=layer)).errors[0]


def test_an_unknown_element_suggests_close_names():
    error = _validate(_p(element="Lantern")).errors[0]

    assert "unknown element 'Lantern'" in error and "'Lanterns'" in error


def test_a_submodel_element_is_rejected():
    assert "submodel" in _validate(_p(element="Pipe 1/Top")).errors[0]


def test_a_slash_name_without_a_real_parent_model_is_an_unknown_element():
    error = _validate(_p(element="Nope/Top")).errors[0]

    assert "unknown element 'Nope/Top'" in error and "submodel" not in error


def test_a_misspelt_placement_key_is_an_error():
    error = _validate(_p(pallete={"colors": ["#FFFFFF"]})).errors[0]

    assert "unknown key 'pallete'" in error and "'palette'" in error


def test_a_misspelt_palette_key_is_an_error():
    error = _validate(_p(palette={"colors": ["#FFFFFF"], "brightnes": 50})).errors[0]

    assert "unknown key 'brightnes'" in error and "'brightness'" in error


def test_an_unknown_effect_suggests_close_names():
    error = _validate(_p(effect="Colour Wash")).errors[0]

    assert "unknown effect 'Colour Wash'" in error and "'Color Wash'" in error


def test_chase_points_at_singlestrand_not_a_lookalike():
    error = _validate(_p(effect="Chase")).errors[0]

    assert "unknown effect 'Chase'; did you mean 'SingleStrand'?" in error
    assert "E_NOTEBOOK_SSEFFECT_TYPE=Chase" in error
    assert "Shape" not in error


def test_other_effect_aliases_suggest_their_target():
    error = _validate(_p(effect="ColorWash")).errors[0]

    assert "unknown effect 'ColorWash'; did you mean 'Color Wash'?" in error
    assert "SingleStrand" not in error


def test_effect_names_come_from_the_given_set():
    result = validate_plan([_p(effect="Custom Thing")], SHOW, 20000, XLIGHTS_EFFECT_NAMES | {"Custom Thing"})

    assert result.errors == []


def test_a_settings_map_keeps_its_order_and_writes_booleans_as_digits():
    result = _validate(_p(settings={"E_CHOICE_Chase_Type1": "Left-Right", "B_X": True, "E_N": 3}))

    assert list(result.placements[0].settings.items()) == [
        ("E_CHOICE_Chase_Type1", "Left-Right"), ("B_X", "1"), ("E_N", "3"),
    ]


def test_a_settings_value_with_a_comma_is_an_error():
    assert "comma" in _validate(_p(settings={"E_TEXTCTRL_Text": "a,b"})).errors[0]


def test_a_raw_settings_string_is_split_on_the_first_equals():
    result = _validate(_p(settings="E_A=1,E_VALUECURVE_B=Active=TRUE|Min=1|"))

    assert result.placements[0].settings == {"E_A": "1", "E_VALUECURVE_B": "Active=TRUE|Min=1|"}


@pytest.mark.parametrize(
    "settings",
    [{"E_A": None}, {"E_A": [1]}, {"E_A": {"x": 1}}, {"E_A": float("nan")}, {"E_A": float("inf")}, {1: "x"}],
)
def test_settings_maps_only_take_scalar_values_and_string_keys(settings):
    assert "settings" in _validate(_p(settings=settings)).errors[0]


def test_settings_maps_accept_finite_floats():
    assert _validate(_p(settings={"E_A": 1.5})).placements[0].settings == {"E_A": "1.5"}


@pytest.mark.parametrize("settings", ["E_A=1, E_B=2", {" E_X ": 1}, {"E X": 1}, "E_A=1,\tE_B=2"])
def test_settings_keys_cannot_contain_whitespace(settings):
    error = _validate(_p(settings=settings)).errors[0]

    assert "invalid settings key" in error and "no spaces" in error


@pytest.mark.parametrize("settings", ["E_A=1,oops", "=1", "E_A=1,E_A=2", 5])
def test_malformed_settings_are_errors(settings):
    assert "settings" in _validate(_p(settings=settings)).errors[0]


def test_a_palette_maps_colours_brightness_and_sparkles():
    result = _validate(_p(palette={"colors": ["#7fe7ff", "#00C8FF"], "brightness": 80, "sparkles": 30}))

    palette = result.placements[0].palette
    assert palette.colors == ["#7FE7FF", "#00C8FF"]
    assert palette.active_colors == [1, 2]
    assert (palette.brightness, palette.sparkle_frequency) == (80, 30)


def test_no_palette_leaves_the_default_to_the_writer():
    assert _validate(_p()).placements[0].palette is None


@pytest.mark.parametrize(
    "palette",
    [
        "red",
        {"colors": []},
        {"colors": ["red"]},
        {"colors": ["#FFF"]},
        {"colors": ["#FFFFFF"] * 9},
        {"colors": ["#FFFFFF"], "brightness": 401},
        {"colors": ["#FFFFFF"], "sparkles": -1},
    ],
)
def test_malformed_palettes_are_errors(palette):
    assert "palette" in _validate(_p(palette=palette)).errors[0]


def test_a_placement_must_be_an_object():
    assert "must be an object" in _validate("Door").errors[0]


def test_a_parent_lit_with_a_contained_element_is_a_warning():
    result = _validate(
        _p(element="House", start_ms=0, end_ms=4000),
        _p(element="Roof Edges", start_ms=1000, end_ms=2000),
        _p(element="Roof Left", start_ms=3000, end_ms=5000),
    )

    assert result.errors == []
    assert result.warnings == [
        "1 moment where House and Roof Edges are both lit",
        "1 moment where House and Roof Left are both lit",
    ]


def test_off_does_not_count_as_lit():
    result = _validate(_p(element="House", effect="Off", start_ms=0, end_ms=4000), _p(element="Roof Edges"))

    assert result.warnings == []


def test_parent_child_warnings_list_the_first_ten_pairs():
    pipes = [_p(element=f"Pipe {n}", start_ms=0, end_ms=1000) for n in range(1, 12)]

    result = _validate(_p(element="Everything Flat", start_ms=0, end_ms=1000), *pipes)

    assert len(result.warnings) == 11
    assert result.warnings[-1] == "... and 1 more parent/child pair lit together"
