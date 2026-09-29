"""Validate an effect plan against the show and song before it is written."""

from __future__ import annotations

import difflib
import math
import re
from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field

from xlights_mcp.sequencer.timing import last_frame_ms, to_frame
from xlights_mcp.xlights.layout import contained_elements
from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.palettes import ColorPalette
from xlights_mcp.xlights.xsq_writer import EffectPlacement

MAX_LAYER = 2
_PLACEMENT_KEYS = ("element", "layer", "effect", "start_ms", "end_ms", "settings", "palette")
_PALETTE_KEYS = ("colors", "brightness", "sparkles")
PARENT_CHILD_PAIRS_LISTED = 10
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
    elements = models | {g.name for g in show.model_groups}
    song_end = last_frame_ms(duration_ms)
    indexed: list[tuple[int, EffectPlacement]] = []
    for i, raw in enumerate(plan):
        try:
            placement, rounded, clipped = _placement(raw, models, elements, effect_names, song_end)
        except PlanError as e:
            result.errors.append(f"placement {i}{_describe(raw)}: {e}")
            continue
        result.adjusted["rounded_to_frame"] += rounded
        result.adjusted["clipped_to_end"] += clipped
        indexed.append((i, placement))
    result.errors.extend(_overlaps(indexed))
    result.warnings.extend(_parent_child_warnings([p for _, p in indexed], show))
    result.placements = [p for _, p in indexed]
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
) -> tuple[EffectPlacement, bool, bool]:
    if not isinstance(raw, dict):
        raise PlanError("must be an object")
    _check_keys(raw, _PLACEMENT_KEYS)
    element = _element(raw.get("element"), models, elements)
    layer = raw.get("layer", 0)
    if not _is_int(layer) or not 0 <= layer <= MAX_LAYER:
        raise PlanError(f"layer must be an integer 0-{MAX_LAYER}, got {layer!r}")
    effect = _effect(raw.get("effect"), effect_names)
    start, end, rounded, clipped = _times(raw.get("start_ms"), raw.get("end_ms"), song_end)
    placement = EffectPlacement(
        model_name=element,
        layer=layer,
        effect_name=effect,
        start_time_ms=start,
        end_time_ms=end,
        settings=_settings(raw.get("settings")),
        palette=_palette(raw.get("palette")),
    )
    return placement, rounded, clipped


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
    if "/" in name and name.split("/", 1)[0] in models:
        raise PlanError(f"{name!r} is a submodel; submodel elements aren't supported yet, use a group")
    raise PlanError(f"unknown element {name!r}{_suggest(name, elements)}")


def _effect(name, effect_names: AbstractSet[str]) -> str:
    if not isinstance(name, str) or not name:
        raise PlanError("effect is required")
    if name in effect_names:
        return name
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
        for key, text in pairs:
            if "," in text:
                raise PlanError(f"settings value for {key} contains a comma; xLights separates settings with commas")
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
        if not key or "," in key or "=" in key:
            raise PlanError(f"invalid settings key {key!r}")
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
    if isinstance(value, (str, int, float)):
        return str(value)
    raise PlanError(f"settings value for {key} must be a string, number or boolean, got {value!r}")


def _palette(value) -> ColorPalette | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PlanError("palette must be an object")
    _check_keys(value, _PALETTE_KEYS)
    colors = value.get("colors")
    if not isinstance(colors, list) or not 1 <= len(colors) <= 8:
        raise PlanError("palette.colors must list 1-8 colours")
    bad = next((c for c in colors if not (isinstance(c, str) and _HEX_COLOUR.fullmatch(c))), None)
    if bad is not None:
        raise PlanError(f"palette colours must be #RRGGBB, got {bad!r}")
    return ColorPalette(
        colors=[c.upper() for c in colors],
        active_colors=list(range(1, len(colors) + 1)),
        brightness=_palette_int(value, "brightness", 100, 400),
        sparkle_frequency=_palette_int(value, "sparkles", 0, 200),
    )


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


def _parent_child_warnings(placements: list[EffectPlacement], show: ShowConfig) -> list[str]:
    lit: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for p in placements:
        if p.effect_name != "Off":
            lit[p.model_name].append((p.start_time_ms, p.end_time_ms))
    counts: dict[tuple[str, str], int] = {}
    for parent, members in contained_elements(show).items():
        if parent not in lit:
            continue
        for child in members & lit.keys():
            n = sum(1 for s1, e1 in lit[parent] for s2, e2 in lit[child] if s1 < e2 and s2 < e1)
            if n:
                counts[(parent, child)] = n
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    warnings = [
        f"{n} moment{'s' if n != 1 else ''} where {parent} and {child} are both lit"
        for (parent, child), n in ranked[:PARENT_CHILD_PAIRS_LISTED]
    ]
    extra = len(ranked) - PARENT_CHILD_PAIRS_LISTED
    if extra > 0:
        warnings.append(f"... and {extra} more parent/child pair{'s' if extra != 1 else ''} lit together")
    return warnings
