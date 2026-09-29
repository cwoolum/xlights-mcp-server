"""Validate an effect plan against the show and song before it is written."""

from __future__ import annotations

import difflib
import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import TypeVar

from xlights_mcp.sequencer.timing import last_frame_ms, to_frame
from xlights_mcp.xlights.layout import contained_elements
from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.palettes import MAX_BRIGHTNESS, ColorPalette, brightness_curve_points
from xlights_mcp.xlights.show import is_submodel_ref
from xlights_mcp.xlights.xsq_writer import EffectPlacement

MAX_LAYER = 2
BLEND_MODES: tuple[str, ...] = (
    "Normal", "Effect 1", "Effect 2", "1 is Mask", "2 is Mask", "1 is Unmask", "2 is Unmask",
    "1 is True Unmask", "2 is True Unmask", "1 reveals 2", "2 reveals 1", "Shadow 1 on 2", "Shadow 2 on 1",
    "Layered", "Average", "Bottom-Top", "Left-Right", "Additive", "Subtractive", "Brightness", "Max", "Min",
)
LAYER_METHOD_KEY = "T_CHOICE_LayerMethod"
BRIGHTNESS_CURVE_KEY = "C_VALUECURVE_Brightness"
_BLEND_BY_LOWER = {mode.lower(): mode for mode in BLEND_MODES}
_PLACEMENT_KEYS = ("element", "layer", "effect", "start_ms", "end_ms", "settings", "palette", "blend")
_PALETTE_KEYS = ("colors", "brightness", "sparkles", "music_sparkles")
WARNINGS_LISTED = 10
FULL_COVERAGE_EFFECTS = frozenset({"Color Wash", "Plasma", "On"})
_EFFECT_HINTS = {
    "chase": ("SingleStrand", " (Chase is a SingleStrand mode: E_NOTEBOOK_SSEFFECT_TYPE=Chase)"),
    "vumeter": ("VU Meter", ""),
}
_K = TypeVar("_K")
_HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")


class PlanError(ValueError):
    """A placement that can't be written."""


@dataclass
class ValidatedPlan:
    placements: list[EffectPlacement] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adjusted: dict[str, int] = field(default_factory=lambda: {"rounded_to_frame": 0, "clipped_to_end": 0})


def validate_plan(
    plan: list[object], show: ShowConfig, duration_ms: int, effect_names: AbstractSet[str]
) -> ValidatedPlan:
    result = ValidatedPlan()
    models = {m.name for m in show.models}
    elements = show.element_names
    song_end = last_frame_ms(duration_ms)
    indexed: list[tuple[int, EffectPlacement]] = []
    for i, raw in enumerate(plan):
        try:
            placement, rounded, clipped, curve_warnings = _placement(raw, models, elements, effect_names, song_end)
        except PlanError as e:
            result.errors.append(f"placement {i}{_describe(raw)}: {e}")
            continue
        result.adjusted["rounded_to_frame"] += rounded
        result.adjusted["clipped_to_end"] += clipped
        indexed.append((i, placement))
        result.warnings.extend(f"placement {i}{_describe(raw)}: {w}" for w in curve_warnings)
        palette = placement.palette
        if palette and palette.music_sparkles and palette.sparkle_frequency == 0:
            result.warnings.append(
                f"placement {i}{_describe(raw)}: music_sparkles has no effect while sparkles is 0"
            )
    result.errors.extend(_overlaps(indexed))
    result.placements = [p for _, p in indexed]
    result.warnings.extend(_parent_child_warnings(result.placements, show))
    result.warnings.extend(_layer_cover_warnings(result.placements))
    return result


def _describe(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    return f" ({raw.get('element')!r}, layer {raw.get('layer', 0)}, {raw.get('start_ms')}-{raw.get('end_ms')} ms)"


def _placement(
    raw: object,
    models: set[str],
    elements: set[str],
    effect_names: AbstractSet[str],
    song_end: int,
) -> tuple[EffectPlacement, bool, bool, list[str]]:
    if not isinstance(raw, dict):
        raise PlanError("must be an object")
    _check_keys(raw, _PLACEMENT_KEYS)
    element = _element(raw.get("element"), models, elements)
    layer = raw.get("layer", 0)
    if not _is_int(layer) or not 0 <= layer <= MAX_LAYER:
        raise PlanError(f"layer must be an integer 0-{MAX_LAYER}, got {layer!r}")
    effect = _effect(raw.get("effect"), effect_names)
    start, end, rounded, clipped = _times(raw.get("start_ms"), raw.get("end_ms"), song_end)
    settings = _with_blend(_settings(raw.get("settings")), raw.get("blend"))
    palette, curve_warnings = _palette(raw.get("palette"), start, end)
    placement = EffectPlacement(
        model_name=element,
        layer=layer,
        effect_name=effect,
        start_time_ms=start,
        end_time_ms=end,
        settings=settings,
        palette=palette,
    )
    return placement, rounded, clipped, curve_warnings


def _check_keys(mapping: dict, allowed: tuple[str, ...]) -> None:
    for key in mapping:
        if key not in allowed:
            raise PlanError(f"unknown key {key!r}{_suggest(str(key), allowed)}")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _suggest(name: str, choices: Iterable[str]) -> str:
    by_lower = {c.lower(): c for c in choices}
    close = difflib.get_close_matches(name.lower(), list(by_lower), n=3, cutoff=0.6)
    return f"; did you mean {', '.join(repr(by_lower[c]) for c in close)}?" if close else ""


def _element(name, models: set[str], elements: set[str]) -> str:
    if not isinstance(name, str) or not name:
        raise PlanError("element is required")
    if name in elements:
        return name
    if is_submodel_ref(name, models):
        raise PlanError(f"{name!r} is a submodel; submodel elements aren't supported yet, use a group")
    raise PlanError(f"unknown element {name!r}{_suggest(name, elements)}")


def _effect(name, effect_names: AbstractSet[str]) -> str:
    if not isinstance(name, str) or not name:
        raise PlanError("effect is required")
    if name in effect_names:
        return name
    suggestion, note = _EFFECT_HINTS.get(name.lower(), (None, ""))
    if suggestion in effect_names:
        raise PlanError(f"unknown effect {name!r}; did you mean {suggestion!r}?{note}")
    raise PlanError(f"unknown effect {name!r}{_suggest(name, effect_names)}")


def _times(start, end, song_end: int) -> tuple[int, int, bool, bool]:
    for key, value in (("start_ms", start), ("end_ms", end)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise PlanError(f"{key} must be a number of milliseconds, got {value!r}")
    if start < 0:
        raise PlanError(f"start_ms must be >= 0, got {start}")
    frame_start, frame_end = to_frame(start), to_frame(end)
    if frame_start >= song_end:
        raise PlanError(f"starts at or after the song end (last frame {song_end} ms)")
    rounded = (frame_start, frame_end) != (start, end)
    clipped = frame_end > song_end
    frame_end = min(frame_end, song_end)
    if frame_end <= frame_start:
        raise PlanError(f"ends at or before its start after rounding/clipping ({frame_start}-{frame_end} ms)")
    return frame_start, frame_end, rounded, clipped


def _settings(value) -> dict[str, str]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        pairs = [(_settings_key(k), _settings_text(k, v)) for k, v in value.items()]
    elif isinstance(value, str):
        pairs = []
        for part in value.split(","):
            key, sep, text = part.partition("=")
            if not sep:
                raise PlanError(f"malformed settings part {part!r}; expected KEY=VALUE")
            pairs.append((key, text))
    else:
        raise PlanError("settings must be an object or a 'KEY=VALUE,KEY=VALUE' string")
    settings: dict[str, str] = {}
    for key, text in pairs:
        if not key or "," in key or "=" in key or any(c.isspace() for c in key):
            raise PlanError(f"invalid settings key {key!r} (no spaces; separate settings with ',' only)")
        if key == BRIGHTNESS_CURVE_KEY:
            raise PlanError("put brightness curves in palette.brightness, not settings")
        if key in settings:
            raise PlanError(f"settings key {key} appears twice")
        settings[key] = text
    return settings


def _settings_key(key) -> str:
    if not isinstance(key, str):
        raise PlanError(f"settings keys must be strings, got {key!r}")
    return key


def _settings_text(key, value) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float) and not math.isfinite(value):
        raise PlanError(f"settings value for {key} must be finite, got {value!r}")
    if not isinstance(value, (str, int, float)):
        raise PlanError(f"settings value for {key} must be a string, number or boolean, got {value!r}")
    text = str(value)
    if "," in text:
        raise PlanError(f"settings value for {key} contains a comma; xLights separates settings with commas")
    return text


def _with_blend(settings: dict[str, str], blend) -> dict[str, str]:
    raw = settings.get(LAYER_METHOD_KEY)
    if blend is not None and raw is not None:
        raise PlanError(f"use blend or {LAYER_METHOD_KEY}, not both")
    chosen = blend if blend is not None else raw
    if chosen is None:
        return settings
    if not isinstance(chosen, str):
        raise PlanError(f"blend must be one of {', '.join(BLEND_MODES)}, got {chosen!r}")
    canonical = _BLEND_BY_LOWER.get(chosen.lower())
    if canonical is None:
        raise PlanError(f"unknown blend {chosen!r}{_suggest(chosen, BLEND_MODES)}")
    rest = {key: value for key, value in settings.items() if key != LAYER_METHOD_KEY}
    return rest if canonical == "Normal" else {**rest, LAYER_METHOD_KEY: canonical}


def _palette(value, start: int, end: int) -> tuple[ColorPalette | None, list[str]]:
    if value is None:
        return None, []
    if not isinstance(value, dict):
        raise PlanError("palette must be an object")
    _check_keys(value, _PALETTE_KEYS)
    colors = value.get("colors")
    if not isinstance(colors, list) or not 1 <= len(colors) <= 8:
        raise PlanError("palette.colors must list 1-8 colours")
    bad = next((c for c in colors if not (isinstance(c, str) and _HEX_COLOUR.fullmatch(c))), None)
    if bad is not None:
        raise PlanError(f"palette colours must be #RRGGBB, got {bad!r}")
    brightness = value.get("brightness", 100)
    curve, warnings = None, []
    if isinstance(brightness, list):
        curve, warnings = brightness_curve_points(_curve_points(brightness, start, end), start, end)
        brightness = 100
    else:
        brightness = _palette_int(value, "brightness", 100, MAX_BRIGHTNESS)
    palette = ColorPalette(
        colors=[c.upper() for c in colors],
        active_colors=list(range(1, len(colors) + 1)),
        brightness=brightness,
        brightness_curve=curve,
        sparkle_frequency=_palette_int(value, "sparkles", 0, 200),
        music_sparkles=_music_sparkles(value.get("music_sparkles", False)),
    )
    return palette, warnings


def _is_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _curve_points(points: list, start: int, end: int) -> list[tuple[int, float]]:
    if not all(isinstance(p, (list, tuple)) and len(p) == 2 and all(_is_number(n) for n in p) for p in points):
        raise PlanError("palette.brightness points must be [t_ms, value] pairs")
    if len(points) < 2:
        raise PlanError("palette.brightness needs at least 2 points")
    framed = []
    for t, level in points:
        frame = to_frame(t)
        if not start <= frame <= end:
            raise PlanError(f"palette.brightness point {t} is outside the placement ({start}-{end} ms)")
        if framed and frame < framed[-1][0]:
            raise PlanError("palette.brightness point times must not decrease")
        if not 0 <= level <= MAX_BRIGHTNESS:
            raise PlanError(f"palette.brightness values must be 0-{MAX_BRIGHTNESS}, got {level}")
        framed.append((frame, level))
    return framed


def _music_sparkles(value) -> bool:
    if not isinstance(value, bool):
        raise PlanError(f"palette.music_sparkles must be true or false, got {value!r}")
    return value


def _palette_int(palette: dict, key: str, default: int, upper: int) -> int:
    value = palette.get(key, default)
    if not _is_int(value) or not 0 <= value <= upper:
        raise PlanError(f"palette.{key} must be an integer 0-{upper}, got {value!r}")
    return value


def _overlaps(indexed: list[tuple[int, EffectPlacement]]) -> list[str]:
    by_track: dict[tuple[str, int], list[tuple[int, EffectPlacement]]] = defaultdict(list)
    for i, p in indexed:
        by_track[(p.model_name, p.layer)].append((i, p))
    errors = []
    for (element, layer), items in by_track.items():
        items.sort(key=lambda item: item[1].start_time_ms)
        prev_i, prev = items[0]
        for i, p in items[1:]:
            if p.start_time_ms < prev.end_time_ms:
                a, b = sorted(((prev_i, prev), (i, p)), key=lambda item: item[0])
                errors.append(
                    f"placements {a[0]} and {b[0]} overlap on {element!r} layer {layer}: "
                    f"{a[1].start_time_ms}-{a[1].end_time_ms} ms and {b[1].start_time_ms}-{b[1].end_time_ms} ms"
                )
            if p.end_time_ms > prev.end_time_ms:
                prev_i, prev = i, p
    return errors


def _lit_by_element(placements: list[EffectPlacement]) -> dict[str, list[EffectPlacement]]:
    lit: dict[str, list[EffectPlacement]] = defaultdict(list)
    for p in placements:
        if p.effect_name != "Off":
            lit[p.model_name].append(p)
    return lit


def _parent_child_warnings(placements: list[EffectPlacement], show: ShowConfig) -> list[str]:
    lit = _lit_by_element(placements)
    counts: dict[tuple[str, str], int] = {}
    for parent, members in contained_elements(show).items():
        if parent not in lit:
            continue
        for child in members & lit.keys():
            n = sum(
                1 for a in lit[parent] for b in lit[child]
                if a.start_time_ms < b.end_time_ms and b.start_time_ms < a.end_time_ms
            )
            if n:
                counts[(parent, child)] = n
    return _listed(
        counts,
        lambda pair, n: f"{_plural(n, 'moment')} where {pair[0]} and {pair[1]} are both lit",
        lambda extra: f"... and {_plural(extra, 'more parent/child pair')} lit together",
    )


def _layer_cover_warnings(placements: list[EffectPlacement]) -> list[str]:
    covers: dict[tuple[str, int, int], list[str]] = defaultdict(list)
    for element, items in _lit_by_element(placements).items():
        bases = [p for p in items if p.effect_name in FULL_COVERAGE_EFFECTS and LAYER_METHOD_KEY not in p.settings]
        for base in bases:
            for below in items:
                if (
                    below.layer > base.layer
                    and base.start_time_ms <= below.start_time_ms
                    and below.end_time_ms <= base.end_time_ms
                ):
                    covers[(element, base.layer, below.layer)].append(base.effect_name)
    return _listed(
        {key: len(effects) for key, effects in covers.items()},
        lambda key, n: (
            f"{_plural(n, 'effect')} on {key[0]} layer {key[2]} completely hidden by "
            f"{covers[key][0]} on layer {key[1]} "
            "(layer 0 is drawn on top: put bases on the highest layer, or give the upper effect a blend)"
        ),
        lambda extra: f"... and {_plural(extra, 'more hidden layer pair')}",
    )


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _listed(
    counts: dict[_K, int], line: Callable[[_K, int], str], overflow: Callable[[int], str]
) -> list[str]:
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = [line(key, n) for key, n in ranked[:WARNINGS_LISTED]]
    if len(ranked) > WARNINGS_LISTED:
        lines.append(overflow(len(ranked) - WARNINGS_LISTED))
    return lines
