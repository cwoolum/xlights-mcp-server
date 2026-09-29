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
