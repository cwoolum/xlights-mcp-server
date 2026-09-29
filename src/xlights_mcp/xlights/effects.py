"""xLights effect definitions and model-type compatibility."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from xlights_mcp.xlights.xsq_writer import is_generated_sequence

XLIGHTS_EFFECT_NAMES: frozenset[str] = frozenset({
    "Off", "On", "Adjust", "Bars", "Butterfly", "Candle", "Circles", "Color Wash", "Curtain",
    "DMX", "Duplicate", "Faces", "Fan", "Fill", "Fire", "Fireworks", "Galaxy", "Garlands",
    "Glediator", "Guitar", "Kaleidoscope", "Life", "Lightning", "Lines", "Liquid", "Marquee",
    "Meteors", "Morph", "Moving Head", "Music", "Piano", "Pictures", "Pinwheel", "Plasma",
    "Ripple", "Servo", "Shader", "Shape", "Shimmer", "Shockwave", "SingleStrand", "Sketch",
    "Snowflakes", "Snowstorm", "Spirals", "Spirograph", "State", "Strobe", "Tendril", "Text",
    "Tree", "Twinkle", "Video", "VU Meter", "Warp", "Wave",
})

_EFFECT_NAME = re.compile(rb'<Effect\b[^>]*?\bname="([^"]+)"')
_HEAD_BYTES = 4096


class EffectDef(BaseModel):
    """Definition of an xLights effect."""

    name: str
    description: str = ""
    best_for: list[str] = Field(default_factory=list)  # model categories
    musical_use: list[str] = Field(default_factory=list)  # when to use musically
    default_settings: dict[str, str] = Field(default_factory=dict)


# Comprehensive effect library based on analysis of existing sequences
EFFECT_LIBRARY: list[EffectDef] = [
    EffectDef(
        name="On",
        description="Solid color fill — static on state",
        best_for=["all"],
        musical_use=["sustained", "background", "accent"],
    ),
    EffectDef(
        name="Twinkle",
        description="Random pixel twinkling/sparkle effect",
        best_for=["custom", "tree", "single_line", "arch"],
        musical_use=["gentle", "ambient", "verse", "quiet_section"],
    ),
    EffectDef(
        name="Shimmer",
        description="Rapid on/off shimmer across all pixels",
        best_for=["single_line", "poly_line", "custom"],
        musical_use=["sustained_note", "building", "transition"],
    ),
    EffectDef(
        name="Shockwave",
        description="Expanding circular wave from center point",
        best_for=["custom", "tree", "arch"],
        musical_use=["beat_hit", "bass_drop", "accent", "downbeat"],
    ),
    EffectDef(
        name="Morph",
        description="Smooth color/position transition effect",
        best_for=["single_line", "poly_line", "arch"],
        musical_use=["beat_hit", "quick_accent", "transition"],
    ),
    EffectDef(
        name="SingleStrand",
        description="Chase/runner effect along a single strand (includes chase, fireworks, etc.)",
        best_for=["arch", "single_line", "poly_line"],
        musical_use=["rhythmic", "beat_sync", "running", "energetic", "chorus"],
    ),
    EffectDef(
        name="Circles",
        description="Animated circles/bubbles pattern",
        best_for=["custom", "tree"],
        musical_use=["playful", "moderate_energy", "verse"],
    ),
    EffectDef(
        name="Plasma",
        description="Flowing plasma/lava lamp effect",
        best_for=["custom", "tree", "arch"],
        musical_use=["ambient", "sustained", "intro", "bridge"],
    ),
    EffectDef(
        name="Pinwheel",
        description="Rotating pinwheel/spiral pattern",
        best_for=["tree", "custom"],
        musical_use=["sustained", "building", "chorus"],
    ),
    EffectDef(
        name="Spirals",
        description="Spiral pattern wrapping around a tree or cylinder",
        best_for=["tree"],
        musical_use=["sustained", "chorus", "building"],
    ),
    EffectDef(
        name="Meteors",
        description="Falling/flying meteor trails",
        best_for=["tree", "single_line", "custom"],
        musical_use=["high_energy", "climax", "chorus", "fills"],
    ),
    EffectDef(
        name="Warp",
        description="Pixel distortion/warp effect on layers below",
        best_for=["custom", "tree"],
        musical_use=["transition", "dramatic", "bridge"],
    ),
    EffectDef(
        name="Faces",
        description="Lip-sync / singing face animation (needs phoneme data)",
        best_for=["custom"],
        musical_use=["vocal_section", "singing_prop"],
    ),
    EffectDef(
        name="Color Wash",
        description="Smooth color gradient wash across the model",
        best_for=["all"],
        musical_use=["ambient", "verse", "gentle", "background"],
    ),
    EffectDef(
        name="Fire",
        description="Flickering fire/flame effect",
        best_for=["custom", "tree", "single_line"],
        musical_use=["dramatic", "building", "intense"],
    ),
    EffectDef(
        name="Butterfly",
        description="Symmetrical butterfly wing pattern",
        best_for=["custom", "tree"],
        musical_use=["ambient", "gentle", "verse"],
    ),
    EffectDef(
        name="Marquee",
        description="Theater marquee chase around border",
        best_for=["window", "poly_line", "custom"],
        musical_use=["rhythmic", "playful", "accent"],
    ),
    EffectDef(
        name="Strobe",
        description="Rapid strobe/flash effect",
        best_for=["all"],
        musical_use=["climax", "hit", "accent", "bass_drop"],
    ),
    EffectDef(
        name="Snowflakes",
        description="Falling snowflake animation",
        best_for=["custom", "tree"],
        musical_use=["gentle", "ambient", "christmas_theme"],
    ),
    EffectDef(
        name="Curtain",
        description="Opening/closing curtain reveal",
        best_for=["custom", "tree"],
        musical_use=["intro", "transition", "reveal"],
    ),
    EffectDef(
        name="Bars",
        description="Horizontal or vertical color bars",
        best_for=["custom", "tree", "arch"],
        musical_use=["rhythmic", "beat_sync", "energetic"],
    ),
    EffectDef(
        name="Galaxy",
        description="Swirling galaxy/nebula pattern",
        best_for=["tree", "custom"],
        musical_use=["ambient", "sustained", "bridge"],
    ),
]


# Musical feature → effect mapping
MUSICAL_EFFECT_MAP = {
    "strong_beat": ["Shockwave", "Morph", "Strobe"],
    "beat_sync": ["SingleStrand", "Bars", "Marquee"],
    "bass_drop": ["Shockwave", "Strobe", "Fire"],
    "high_energy": ["SingleStrand", "Meteors", "Bars"],
    "low_energy": ["Twinkle", "Shimmer", "Color Wash", "Snowflakes"],
    "sustained": ["Plasma", "Pinwheel", "Spirals", "Galaxy", "Butterfly"],
    "vocal": ["Faces"],
    "transition": ["Warp", "Curtain", "Morph"],
    "intro": ["Curtain", "Color Wash", "Plasma"],
    "outro": ["Twinkle", "Color Wash", "Shimmer"],
    "chorus": ["SingleStrand", "Shockwave", "Meteors", "Pinwheel"],
    "verse": ["Twinkle", "Color Wash", "Circles", "Butterfly"],
    "bridge": ["Plasma", "Warp", "Galaxy"],
}


# Model category → best effects
MODEL_EFFECT_MAP = {
    "arch": ["SingleStrand", "Color Wash", "Morph", "Shimmer", "Plasma"],
    "tree": ["Spirals", "Pinwheel", "Meteors", "Circles", "Shockwave", "Plasma", "Galaxy"],
    "single_line": ["SingleStrand", "Morph", "Shimmer", "Color Wash"],
    "poly_line": ["SingleStrand", "Shimmer", "Twinkle", "Morph"],
    "window": ["Marquee", "Color Wash", "On", "Curtain"],
    "custom": ["Shockwave", "Circles", "Plasma", "Twinkle", "Warp", "Fire", "Faces"],
    "other": ["Color Wash", "Twinkle", "On", "Shimmer"],
}


def get_effect_library() -> list[dict]:
    """Return the complete effect library as dicts for MCP tool response."""
    return [e.model_dump() for e in EFFECT_LIBRARY]


def get_effects_for_model(model_category: str) -> list[str]:
    """Get recommended effect names for a model category."""
    return MODEL_EFFECT_MAP.get(model_category, MODEL_EFFECT_MAP["other"])


def get_effects_for_musical_feature(feature: str) -> list[str]:
    """Get recommended effects for a musical feature."""
    return MUSICAL_EFFECT_MAP.get(feature, [])


@lru_cache(maxsize=512)
def _effect_names_in(path: Path, mtime_ns: int, size: int) -> frozenset[str]:
    with path.open("rb") as f:
        head = f.read(_HEAD_BYTES)
        if is_generated_sequence(head):
            return frozenset()
        data = head + f.read()
    return frozenset(m.decode("utf-8", "replace") for m in _EFFECT_NAME.findall(data))


def known_effect_names(show_path: Path | None) -> frozenset[str]:
    """XLIGHTS_EFFECT_NAMES plus every effect name used by the show folder's .xsq files."""
    names = set(XLIGHTS_EFFECT_NAMES)
    if show_path:
        for xsq in show_path.glob("*.xsq"):
            try:
                stat = xsq.stat()
                names |= _effect_names_in(xsq, stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
    return frozenset(names)
