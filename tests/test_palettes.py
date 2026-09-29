"""ColorPalette serialisation."""

from __future__ import annotations

from xlights_mcp.xlights.palettes import DEFAULT_PALETTE, ColorPalette, brightness_curve_points


def test_brightness_is_omitted_at_its_default():
    parts = ColorPalette(colors=["#FF0000"], active_colors=[1]).to_xlights_string().split(",")

    assert not any(p.startswith("C_SLIDER_Brightness") for p in parts)


def test_brightness_is_written_when_changed():
    parts = ColorPalette(colors=["#FF0000"], active_colors=[1], brightness=40).to_xlights_string().split(",")

    assert "C_SLIDER_Brightness=40" in parts


def test_default_palette_is_white_in_slot_one_only():
    parts = DEFAULT_PALETTE.to_xlights_string().split(",")

    assert "C_BUTTON_Palette1=#FFFFFF" in parts
    assert [p for p in parts if p.startswith("C_CHECKBOX_")] == ["C_CHECKBOX_Palette1=1"]


def test_music_sparkles_is_written_when_set_and_omitted_by_default():
    palette = ColorPalette(colors=["#FF0000"], active_colors=[1], sparkle_frequency=20)

    assert "C_CHECKBOX_MusicSparkles=1" not in palette.to_xlights_string().split(",")
    parts = palette.model_copy(update={"music_sparkles": True}).to_xlights_string().split(",")
    assert parts[-1] == "C_CHECKBOX_MusicSparkles=1"
    assert parts.index("C_CHECKBOX_MusicSparkles=1") == parts.index("C_SLIDER_SparkleFrequency=20") + 1


def _curve_string(points_ms, start=0, end=10000) -> str:
    curve, _ = brightness_curve_points(points_ms, start, end)
    palette = ColorPalette(colors=["#FF0000"], active_colors=[1], brightness_curve=curve)
    return palette.to_xlights_string()


def test_a_ramp_becomes_two_points_and_replaces_the_brightness_slider():
    curve, warnings = brightness_curve_points([(0, 100), (10000, 300)], 0, 10000)
    text = _curve_string([(0, 100), (10000, 300)])

    assert curve == [(0.0, 100), (1.0, 300)] and warnings == []
    assert "Values=0.000:0.2500;1.000:0.7500|" in text
    assert "Type=Custom|Min=0.00|Max=400.00|RV=TRUE|" in text
    assert "C_SLIDER_Brightness" not in text


def test_the_curve_ignores_the_plain_brightness():
    palette = ColorPalette(colors=["#FF0000"], active_colors=[1], brightness=40, brightness_curve=[(0.0, 100), (1.0, 300)])

    assert "C_SLIDER_Brightness" not in palette.to_xlights_string()


def test_a_step_puts_its_second_point_one_slot_later():
    curve, warnings = brightness_curve_points([(0, 100), (5000, 100), (5000, 250), (10000, 250)], 0, 10000)

    assert [x * 200 for x, _ in curve] == [0, 100, 101, 200]
    assert [level for _, level in curve] == [100, 100, 250, 250]
    assert warnings == []


def test_missing_end_points_are_added_holding_the_first_and_last_values():
    curve, _ = brightness_curve_points([(2000, 100), (8000, 200)], 0, 10000)

    assert [(round(x * 200), level) for x, level in curve] == [(0, 100), (40, 100), (160, 200), (200, 200)]


def test_closely_spaced_points_on_a_long_effect_warn_about_snapping_and_merging():
    _, warnings = brightness_curve_points([(0, 100), (1000, 120), (1030, 140), (20000, 140)], 0, 20000)

    assert "brightness curve points snap to 100 ms steps on this 20.0 s effect" in warnings
    assert "brightness points closer than one curve slot (100 ms) were merged" in warnings


def test_points_landing_on_one_slot_keep_the_later_value():
    curve, _ = brightness_curve_points([(0, 100), (1000, 120), (1030, 140), (20000, 140)], 0, 20000)

    assert {round(x * 200): level for x, level in curve}[10] == 140


def test_a_short_effect_snaps_without_warning():
    _, warnings = brightness_curve_points([(0, 100), (1234, 200), (4000, 300)], 0, 4000)

    assert warnings == []


def test_slot_one_is_written_with_its_half_slot_position():
    assert "Values=0.000:0.2500;0.005:0.5000;1.000:0.5000|" in _curve_string([(0, 100), (50, 200), (10000, 200)])


def test_a_point_just_after_a_step_merges_into_the_steps_second_slot_and_keeps_the_curve_ordered():
    curve, warnings = brightness_curve_points([(0, 100), (5000, 100), (5000, 250), (5025, 300), (10000, 300)], 0, 10000)

    assert [round(x * 200) for x, _ in curve] == [0, 100, 101, 200]
    assert [level for _, level in curve] == [100, 100, 300, 300]
    assert "brightness points closer than one curve slot (50 ms) were merged" in warnings


def test_a_step_at_the_very_end_uses_the_last_two_slots():
    curve, _ = brightness_curve_points([(0, 100), (10000, 100), (10000, 300)], 0, 10000)

    assert [(round(x * 200), level) for x, level in curve] == [(0, 100), (199, 100), (200, 300)]


def test_an_end_step_that_displaces_slot_199_warns():
    _, warnings = brightness_curve_points([(0, 100), (9950, 50), (10000, 100), (10000, 300)], 0, 10000)

    assert "brightness points closer than one curve slot (50 ms) were merged" in warnings


def test_slots_round_half_up():
    curve, warnings = brightness_curve_points([(0, 100), (25, 200), (75, 300), (10000, 300)], 0, 10000)

    assert [round(x * 200) for x, _ in curve] == [0, 1, 2, 200]
    assert warnings == []
