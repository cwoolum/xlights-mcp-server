"""validate_plan: one test per rule in the spec's rule table."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.sequencer.plan import BLEND_MODES, validate_plan
from xlights_mcp.xlights.effects import XLIGHTS_EFFECT_NAMES
from xlights_mcp.xlights.show import load_show_config

SHOW = load_show_config(Path(__file__).parent / "fixtures" / "show_groups")


def _p(**over) -> dict:
    return {"element": "Door", "layer": 0, "effect": "On", "start_ms": 1000, "end_ms": 2000, **over}


def _validate(*placements, duration_ms: int = 20000, effect_names=XLIGHTS_EFFECT_NAMES):
    return validate_plan(list(placements), SHOW, duration_ms, effect_names)


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
    result = _validate(_p(effect="Custom Thing"), effect_names=XLIGHTS_EFFECT_NAMES | {"Custom Thing"})

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


def test_blend_sets_the_layer_method_setting():
    placement = _validate(_p(blend="Additive", settings={"E_A": "1"})).placements[0]

    assert placement.settings == {"E_A": "1", "T_CHOICE_LayerMethod": "Additive"}


@pytest.mark.parametrize("blend", [None, "Normal", "normal"])
def test_normal_blend_and_no_blend_write_nothing(blend):
    extra = {} if blend is None else {"blend": blend}

    assert _validate(_p(**extra)).placements[0].settings == {}


def test_blend_is_matched_case_insensitively_and_normalised():
    assert _validate(_p(blend="1 REVEALS 2")).placements[0].settings["T_CHOICE_LayerMethod"] == "1 reveals 2"


@pytest.mark.parametrize("key, expected", [("additive", "Additive"), ("2 IS MASK", "2 is Mask")])
def test_a_raw_layer_method_setting_is_normalised_like_blend(key, expected):
    placement = _validate(_p(settings={"E_A": "1", "T_CHOICE_LayerMethod": key})).placements[0]

    assert placement.settings == {"E_A": "1", "T_CHOICE_LayerMethod": expected}


def test_a_raw_normal_layer_method_is_dropped():
    assert _validate(_p(settings="T_CHOICE_LayerMethod=normal")).placements[0].settings == {}


def test_an_unknown_blend_suggests_close_names():
    error = _validate(_p(blend="Additiv")).errors[0]

    assert "unknown blend 'Additiv'" in error and "'Additive'" in error


def test_an_unknown_raw_layer_method_is_the_same_error():
    error = _validate(_p(settings={"T_CHOICE_LayerMethod": "additiv"})).errors[0]

    assert "unknown blend 'additiv'" in error and "'Additive'" in error


def test_blend_must_be_a_string():
    assert "blend" in _validate(_p(blend=3)).errors[0]


def test_blend_and_the_layer_method_setting_together_are_an_error():
    error = _validate(_p(blend="Additive", settings={"T_CHOICE_LayerMethod": "Max"})).errors[0]

    assert "use blend or T_CHOICE_LayerMethod, not both" in error


def test_blend_modes_are_the_xlights_list():
    used_in_the_users_sequences = {
        "Additive", "Layered", "2 is Unmask", "Effect 1", "2 is Mask", "1 reveals 2", "2 reveals 1",
        "1 is True Unmask", "Max", "Average", "1 is Unmask", "Effect 2", "Subtractive", "Bottom-Top", "1 is Mask",
    }

    assert len(BLEND_MODES) == 22 and len(set(BLEND_MODES)) == 22
    assert BLEND_MODES[0] == "Normal"
    assert used_in_the_users_sequences <= set(BLEND_MODES)


def test_music_sparkles_maps_onto_the_palette():
    palette = _validate(_p(palette={"colors": ["#FFFFFF"], "music_sparkles": True})).placements[0].palette

    assert palette.music_sparkles is True
    assert _validate(_p(palette={"colors": ["#FFFFFF"]})).placements[0].palette.music_sparkles is False


def test_music_sparkles_without_sparkles_is_a_warning():
    result = _validate(
        _p(palette={"colors": ["#FFFFFF"], "music_sparkles": True}),
        _p(start_ms=2000, end_ms=3000, palette={"colors": ["#FFFFFF"], "music_sparkles": True, "sparkles": 30}),
    )

    assert result.errors == []
    assert result.warnings == [
        "placement 0 ('Door', layer 0, 1000-2000 ms): music_sparkles has no effect while sparkles is 0"
    ]


@pytest.mark.parametrize("value", [1, "true", None])
def test_music_sparkles_must_be_a_boolean(value):
    error = _validate(_p(palette={"colors": ["#FFFFFF"], "music_sparkles": value})).errors[0]

    assert "music_sparkles" in error


def test_a_wash_over_a_lower_effect_warns_that_it_hides_it():
    result = _validate(
        _p(layer=0, effect="Color Wash", start_ms=0, end_ms=4000),
        _p(layer=1, effect="On", start_ms=1000, end_ms=2000),
    )

    assert result.errors == []
    assert result.warnings == [
        (
            "1 effect on Door layer 1 completely hidden by Color Wash on layer 0 "
            "(layer 0 is drawn on top: put bases on the highest layer, or give the upper effect a blend)"
        )
    ]


@pytest.mark.parametrize(
    "upper, lower, warns",
    [
        ({"effect": "Color Wash", "start_ms": 0, "end_ms": 4000}, {"effect": "Twinkle", "end_ms": 2000}, True),
        ({"effect": "Color Wash", "start_ms": 0, "end_ms": 4000}, {"effect": "On", "start_ms": 0, "end_ms": 4000}, True),
        (
            {"effect": "Plasma", "settings": {"T_CHOICE_LayerMethod": "normal"}, "start_ms": 0, "end_ms": 4000},
            {"effect": "Twinkle"},
            True,
        ),
        ({"effect": "On", "start_ms": 1000, "end_ms": 1100}, {"effect": "Color Wash", "start_ms": 0, "end_ms": 4000}, False),
        ({"effect": "Twinkle"}, {"effect": "Color Wash", "start_ms": 0, "end_ms": 4000}, False),
        ({"effect": "Color Wash", "start_ms": 1000, "end_ms": 4000}, {"effect": "Twinkle", "start_ms": 3000, "end_ms": 5000}, False),
        ({"effect": "Color Wash", "start_ms": 1000, "end_ms": 4000}, {"effect": "Twinkle", "start_ms": 0, "end_ms": 1500}, False),
        ({"effect": "Color Wash", "start_ms": 0, "end_ms": 1000}, {"effect": "On", "start_ms": 1000, "end_ms": 2000}, False),
        ({"effect": "Color Wash", "blend": "Additive", "start_ms": 0, "end_ms": 4000}, {"effect": "On"}, False),
        (
            {"effect": "Color Wash", "settings": {"T_CHOICE_LayerMethod": "additive"}, "start_ms": 0, "end_ms": 4000},
            {"effect": "On"},
            False,
        ),
        ({"effect": "Color Wash", "start_ms": 0, "end_ms": 4000}, {"effect": "Off"}, False),
        ({"effect": "Color Wash", "start_ms": 0, "end_ms": 4000}, {"element": "Tree 6ft"}, False),
    ],
    ids=[
        "twinkle-under-wash", "on-under-wash", "raw-normal-layer-method", "short-on-over-wash",
        "accent-over-wash", "starts-inside", "ends-inside", "touching", "blended", "raw-blended",
        "off-below", "other-element",
    ],
)
def test_layer_cover_warns_only_when_the_upper_effect_hides_the_whole_lower_one(upper, lower, warns):
    result = _validate(
        _p(layer=0, **{"start_ms": 1000, "end_ms": 2000, **upper}),
        _p(layer=1, **{"start_ms": 1000, "end_ms": 2000, **lower}),
    )

    assert result.errors == []
    assert len(result.warnings) == (1 if warns else 0)


def test_hidden_effects_are_counted_per_layer_pair():
    result = _validate(
        _p(layer=0, effect="Plasma", start_ms=0, end_ms=4000),
        _p(layer=1, effect="Twinkle", start_ms=0, end_ms=1000),
        _p(layer=1, effect="Twinkle", start_ms=2000, end_ms=3000),
        _p(layer=2, effect="Twinkle", start_ms=0, end_ms=1000),
    )

    assert [w.split(" (")[0] for w in result.warnings] == [
        "2 effects on Door layer 1 completely hidden by Plasma on layer 0",
        "1 effect on Door layer 2 completely hidden by Plasma on layer 0",
    ]


def test_layer_cover_warnings_list_the_first_ten_groups():
    placements = [
        _p(element=f"Pipe {n}", layer=0, effect="Color Wash", start_ms=0, end_ms=1000) for n in range(1, 12)
    ] + [_p(element=f"Pipe {n}", layer=1, effect="On", start_ms=0, end_ms=1000) for n in range(1, 12)]

    result = _validate(*placements)

    assert len(result.warnings) == 11
    assert result.warnings[-1] == "... and 1 more hidden layer pair"


def _curve(points, **over) -> dict:
    return _p(palette={"colors": ["#FFFFFF"], "brightness": points}, **over)


def test_a_brightness_curve_becomes_palette_points_across_the_placement():
    result = _validate(_curve([[1000, 100], [1500, 100], [1500, 300], [2000, 300]]))

    assert result.errors == [] and result.warnings == []
    palette = result.placements[0].palette
    assert [(round(x * 200), level) for x, level in palette.brightness_curve] == [
        (0, 100), (100, 100), (101, 300), (200, 300),
    ]


def test_curve_point_times_are_frame_rounded():
    result = _validate(_curve([[1000, 100], [1512, 200], [2000, 200]], start_ms=1000, end_ms=2000))

    assert result.placements[0].palette.brightness_curve[1][0] == pytest.approx(0.5, abs=0.005)


@pytest.mark.parametrize(
    "points",
    [
        [[1000, 100], "x"],
        [[1000, 100], [1500]],
        [[1000, 100], [1500, 100, 1]],
        [[1000, 100], [1500, "high"]],
        [[1000, 100], [True, 100]],
        [[1000, 100], [float("nan"), 100]],
    ],
)
def test_curve_points_must_be_pairs_of_numbers(points):
    assert "palette.brightness points must be [t_ms, value] pairs" in _validate(_curve(points)).errors[0]


def test_a_curve_needs_two_points():
    assert "palette.brightness needs at least 2 points" in _validate(_curve([[1000, 100]])).errors[0]
    assert "palette.brightness needs at least 2 points" in _validate(_curve([])).errors[0]


@pytest.mark.parametrize("t", [900, 2100])
def test_curve_points_outside_the_placement_are_errors(t):
    error = _validate(_curve([[1000, 100], [t, 200]])).errors[0]

    assert f"palette.brightness point {t} is outside the placement (1000-2000 ms)" in error


def test_curve_point_times_must_not_decrease():
    error = _validate(_curve([[1000, 100], [1600, 200], [1400, 300]])).errors[0]

    assert "palette.brightness point times must not decrease" in error


@pytest.mark.parametrize("level", [401, -1])
def test_curve_values_are_limited_to_0_to_400(level):
    error = _validate(_curve([[1000, 100], [2000, level]])).errors[0]

    assert f"palette.brightness values must be 0-400, got {level}" in error


def test_curve_values_may_be_floats():
    assert _validate(_curve([[1000, 100.5], [2000, 250.25]])).errors == []


def test_curve_snap_warnings_carry_the_placement_prefix():
    result = _validate(_curve([[0, 100], [1000, 120], [1040, 140], [20000, 140]], start_ms=0, end_ms=20000))

    assert result.errors == []
    assert any(
        w.startswith("placement 0 ('Door', layer 0, 0-20000 ms): brightness curve points snap to 100 ms steps")
        for w in result.warnings
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"C_VALUECURVE_Brightness": "Active=TRUE"},
        "C_VALUECURVE_Brightness=Active=TRUE|Values=0.000:0.2500",
    ],
)
def test_a_brightness_curve_in_settings_is_rejected(settings):
    error = _validate(_p(settings=settings)).errors[0]

    assert "put brightness curves in palette.brightness, not settings" in error


def test_a_curve_on_a_placement_clipped_to_the_song_end_is_cut_at_the_end():
    result = _validate(_curve([[1000, 100], [2000, 300]], start_ms=1000, end_ms=2000), duration_ms=1500)

    assert result.errors == []
    assert result.placements[0].end_time_ms == 1500
    assert result.placements[0].palette.brightness_curve == [(0.0, 100), (1.0, 200)]


def test_a_clipped_curve_drops_the_points_after_the_song_end():
    points = [[1000, 100], [1400, 100], [1600, 200], [2000, 300]]

    curve = _validate(_curve(points, start_ms=1000, end_ms=2000), duration_ms=1500).placements[0].palette.brightness_curve

    assert [(round(x * 200), level) for x, level in curve] == [(0, 100), (160, 100), (200, 150)]


def test_a_clipped_curve_that_starts_after_the_song_end_points_holds_its_first_value():
    curve = _validate(_curve([[1600, 250], [2000, 300]], start_ms=1000, end_ms=2000), duration_ms=1500).placements[0].palette.brightness_curve

    assert curve == [(0.0, 250), (1.0, 250)]
