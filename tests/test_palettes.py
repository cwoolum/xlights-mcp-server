"""ColorPalette serialisation."""

from __future__ import annotations

from xlights_mcp.xlights.palettes import DEFAULT_PALETTE, ColorPalette


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
