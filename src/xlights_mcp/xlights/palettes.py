"""Color palette management for xLights sequences."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

CURVE_SLOTS = 200
MAX_BRIGHTNESS = 400
_SNAP_WARNING_MS = 25


def brightness_curve_points(
    points_ms: list[tuple[float, float]], start_ms: float, end_ms: float
) -> tuple[list[tuple[float, float]], list[str]]:
    """Snap ``(t_ms, level)`` points to the ``CURVE_SLOTS`` slots across an effect, as ``(x, level)`` pairs with warnings."""
    length = end_ms - start_ms
    slot_ms = length / CURVE_SLOTS
    by_slot: dict[int, float] = {}
    snapped = merged = False
    previous_t: float | None = None
    previous_slot = 0
    for t, level in points_ms:
        slot = round((t - start_ms) / length * CURVE_SLOTS)
        if abs(slot * slot_ms - (t - start_ms)) > _SNAP_WARNING_MS:
            snapped = True
        if t == previous_t:
            slot = min(previous_slot + 1, CURVE_SLOTS)
        if slot in by_slot:
            merged = True
        by_slot[slot] = level
        previous_t, previous_slot = t, slot
    by_slot.setdefault(0, by_slot[min(by_slot)])
    by_slot.setdefault(CURVE_SLOTS, by_slot[max(by_slot)])
    warnings = []
    if snapped:
        warnings.append(
            f"brightness curve points snap to {slot_ms:.0f} ms steps on this {length / 1000:.1f} s effect"
        )
    if merged:
        warnings.append(f"brightness points closer than one curve slot ({slot_ms:.0f} ms) were merged")
    return [(slot / CURVE_SLOTS, by_slot[slot]) for slot in sorted(by_slot)], warnings


class ColorPalette(BaseModel):
    """An xLights color palette for effects."""

    colors: list[str] = Field(default_factory=list)  # hex colors like "#FF0000"
    active_colors: list[int] = Field(default_factory=list)  # which palette slots are active
    sparkle_frequency: int = 0
    sparkle_color: str = ""
    music_sparkles: bool = False
    brightness: int = 100
    brightness_curve: list[tuple[float, float]] | None = None  # (x 0-1 across the effect, level 0-400)

    def to_xlights_string(self) -> str:
        """Serialize to the xLights palette format string."""
        parts = []
        # Palette button colors (up to 8 slots)
        defaults = ["#FFFFFF", "#FF0000", "#00FF00", "#0000FF",
                     "#FFFF00", "#000000", "#00FFFF", "#FF00FF"]
        for i in range(8):
            color = self.colors[i] if i < len(self.colors) else defaults[i]
            parts.append(f"C_BUTTON_Palette{i + 1}={color}")

        # Active color checkboxes
        for idx in self.active_colors:
            parts.append(f"C_CHECKBOX_Palette{idx}=1")

        if self.brightness_curve:
            values = ";".join(f"{x:.3f}:{level / MAX_BRIGHTNESS:.4f}" for x, level in self.brightness_curve)
            parts.append(
                "C_VALUECURVE_Brightness=Active=TRUE|Id=ID_VALUECURVE_Brightness|Type=Custom"
                f"|Min=0.00|Max={MAX_BRIGHTNESS:.2f}|RV=TRUE|Values={values}|"
            )
        elif self.brightness != 100:
            parts.append(f"C_SLIDER_Brightness={self.brightness}")

        # Sparkle
        if self.sparkle_frequency > 0:
            parts.append(f"C_SLIDER_SparkleFrequency={self.sparkle_frequency}")
        if self.music_sparkles:
            parts.append("C_CHECKBOX_MusicSparkles=1")
        if self.sparkle_color:
            parts.append(f"C_COLOURPICKERCTRL_SparklesColour={self.sparkle_color}")

        return ",".join(parts)


DEFAULT_PALETTE = ColorPalette(colors=["#FFFFFF"], active_colors=[1])


# Pre-defined theme palettes
CHRISTMAS_PALETTES = {
    "classic": ColorPalette(
        colors=["#FF0000", "#00FF00", "#FFFFFF"],
        active_colors=[1, 2, 3],
    ),
    "warm": ColorPalette(
        colors=["#FF0000", "#FEB800", "#FFD700", "#FFFFFF"],
        active_colors=[1, 2, 3, 4],
    ),
    "cool": ColorPalette(
        colors=["#0000FF", "#00FFFF", "#FFFFFF", "#C0C0FF"],
        active_colors=[1, 2, 3, 4],
    ),
    "candy_cane": ColorPalette(
        colors=["#FF0000", "#FFFFFF"],
        active_colors=[1, 2],
    ),
    "gold_silver": ColorPalette(
        colors=["#FFD700", "#C0C0C0", "#FFFFFF"],
        active_colors=[1, 2, 3],
    ),
    "icy": ColorPalette(
        colors=["#FFFFFF", "#87CEEB", "#00BFFF", "#ADD8E6"],
        active_colors=[1, 2, 3, 4],
    ),
    "traditional": ColorPalette(
        colors=["#FF0000", "#00FF00", "#FFD700", "#FFFFFF"],
        active_colors=[1, 2, 3, 4],
    ),
}

HALLOWEEN_PALETTES = {
    "classic": ColorPalette(
        colors=["#FF6600", "#800080", "#00FF00", "#000000"],
        active_colors=[1, 2, 3],
    ),
    "spooky": ColorPalette(
        colors=["#800080", "#00FF00", "#FF0000", "#000000"],
        active_colors=[1, 2, 3],
    ),
    "fire": ColorPalette(
        colors=["#FF0000", "#FF6600", "#FFD700", "#FFFFFF"],
        active_colors=[1, 2, 3],
    ),
    "ghostly": ColorPalette(
        colors=["#FFFFFF", "#E0E0FF", "#C0C0FF", "#8080FF"],
        active_colors=[1, 2, 3, 4],
    ),
}

GENERIC_PALETTES = {
    "rainbow": ColorPalette(
        colors=["#FF0000", "#FF8000", "#FFFF00", "#00FF00", "#0000FF", "#8000FF"],
        active_colors=[1, 2, 3, 4, 5, 6],
    ),
    "white": ColorPalette(
        colors=["#FFFFFF"],
        active_colors=[1],
    ),
    "warm_white": ColorPalette(
        colors=["#FFF5E6", "#FFE0B2", "#FFCC80"],
        active_colors=[1, 2, 3],
    ),
}


def get_theme_palettes(theme: str | None) -> dict[str, ColorPalette]:
    """Get palettes appropriate for a theme."""
    if theme and "halloween" in theme.lower():
        return {**HALLOWEEN_PALETTES, **GENERIC_PALETTES}
    elif theme and "christmas" in theme.lower():
        return {**CHRISTMAS_PALETTES, **GENERIC_PALETTES}
    return {**CHRISTMAS_PALETTES, **GENERIC_PALETTES}


COLOR_NAMES: dict[str, str] = {
    "red": "#FF0000", "green": "#00FF00", "blue": "#0000FF", "white": "#FFFFFF",
    "warm white": "#FFE4B5", "yellow": "#FFFF00", "orange": "#FF6600", "gold": "#FFD700",
    "purple": "#800080", "pink": "#FF69B4", "magenta": "#FF00FF", "cyan": "#00FFFF", "ice": "#A5F2F3",
}
MAX_PALETTE_COLORS = 8
_HEX_COLOR = re.compile(r"#[0-9a-f]{6}")
_HINT_SEPARATORS = re.compile(r",|\band\b")


def parse_palette_hint(hint: str) -> tuple[list[str], list[str]]:
    """Colours named in a hint such as "red, green and warm white" or "#FF6600 and purple", plus unrecognised words."""
    colors: list[str] = []
    unknown: list[str] = []
    for phrase in _HINT_SEPARATORS.split(hint.lower()):
        phrase = " ".join(phrase.split())
        if not phrase:
            continue
        color = phrase.upper() if _HEX_COLOR.fullmatch(phrase) else COLOR_NAMES.get(phrase)
        if color is None:
            unknown.append(phrase)
        elif color not in colors:
            colors.append(color)
    return colors[:MAX_PALETTE_COLORS], unknown


def palette_colors(hint: str | None, theme: str | None) -> tuple[list[str], list[str]]:
    """The hint's colours, or the theme's first palette's active colours when the hint names none."""
    colors, unknown = parse_palette_hint(hint) if hint else ([], [])
    if not colors:
        palette = next(iter(get_theme_palettes(theme).values()))
        colors = [palette.colors[i - 1] for i in palette.active_colors]
    return colors, unknown
