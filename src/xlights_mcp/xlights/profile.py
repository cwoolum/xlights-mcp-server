"""Style profile of an .xsq: how many elements are lit together, layering, parents under children."""

from __future__ import annotations

import statistics
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from xlights_mcp.xlights.layout import contained_elements
from xlights_mcp.xlights.models import ShowConfig

SAMPLE_MS = 50
MAX_ELEMENT_ROWS = 20
TOP_EFFECTS = 3

Span = tuple[int, int]


@dataclass
class _Element:
    name: str
    layers: list[list[tuple[str, int, int]]]


def _read(xsq_path: Path) -> tuple[int, list[_Element], list[str]]:
    root = ET.parse(xsq_path).getroot()
    elements: list[_Element] = []
    timing: list[str] = []
    for el in root.iterfind("ElementEffects/Element"):
        name = el.get("name", "")
        if el.get("type") == "timing":
            timing.append(name)
            continue
        layers = [
            [(e.get("name", ""), int(e.get("startTime", "0")), int(e.get("endTime", "0"))) for e in layer.iterfind("Effect")]
            for layer in el.iterfind("EffectLayer")
        ]
        if any(layers):
            elements.append(_Element(name, layers))
    try:
        duration_ms = round(float(root.findtext("head/sequenceDuration", "0")) * 1000)
    except ValueError:
        duration_ms = 0
    if duration_ms <= 0:
        duration_ms = max((end for e in elements for layer in e.layers for _, _, end in layer), default=0)
    return duration_ms, elements, timing


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _length(spans: list[Span]) -> int:
    return sum(end - start for start, end in spans)


def _overlap_length(a: list[Span], b: list[Span]) -> int:
    total = i = j = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        total += max(0, hi - lo)
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def _lit_at_once(lit: dict[str, list[Span]], duration_ms: int) -> np.ndarray:
    samples = max(1, -(-duration_ms // SAMPLE_MS))
    steps = np.zeros(samples + 1, dtype=int)
    for spans in lit.values():
        for start, end in spans:
            first, stop = -(-start // SAMPLE_MS), -(-min(end, duration_ms) // SAMPLE_MS)
            if stop > first:
                steps[first] += 1
                steps[stop] -= 1
    return np.cumsum(steps)[:samples]


def _overlaps(elements: list[_Element]) -> int:
    count = 0
    for element in elements:
        for layer in element.layers:
            latest_end = None
            for _, start, end in sorted(layer, key=lambda e: e[1]):
                if latest_end is not None and start < latest_end:
                    count += 1
                latest_end = end if latest_end is None else max(latest_end, end)
    return count


def profile_sequence(xsq_path: Path, show: ShowConfig) -> dict:
    """Concurrency, darkness, layering and parent/child overlap of a sequence, per the active show."""
    duration_ms, elements, timing_tracks = _read(xsq_path)
    groups = {g.name for g in show.model_groups}
    models = {m.name for m in show.models}
    lit = {
        e.name: _merge([(s, t) for layer in e.layers for name, s, t in layer if name != "Off" and t > s])
        for e in elements
    }

    rows = []
    for e in elements:
        effects = [effect for layer in e.layers for effect in layer]
        rows.append({
            "element": e.name,
            "kind": "group" if e.name in groups else "model" if e.name in models else "unknown",
            "layers": [i for i, layer in enumerate(e.layers) if layer],
            "effects": len(effects),
            "median_ms": round(statistics.median(end - start for _, start, end in effects)),
            "lit_share": round(_length(lit[e.name]) / duration_ms, 2) if duration_ms else 0.0,
            "top_effects": [name for name, _ in Counter(name for name, _, _ in effects).most_common(TOP_EFFECTS)],
        })
    rows.sort(key=lambda r: (-r["effects"], r["element"]))

    counts = _lit_at_once(lit, duration_ms)
    kinds = Counter(r["kind"] for r in rows)

    parent_share = {}
    for parent, members in contained_elements(show).items():
        spans = lit.get(parent)
        inside = _merge([span for m in members if m in lit for span in lit[m]])
        if spans and inside:
            parent_share[parent] = round(_overlap_length(spans, inside) / _length(spans), 2)

    extra = rows[MAX_ELEMENT_ROWS:]
    return {
        "file": xsq_path.name,
        "duration_ms": duration_ms,
        "elements_with_effects": {"groups": kinds["group"], "models": kinds["model"], "unknown": kinds["unknown"]},
        "total_effects": sum(r["effects"] for r in rows),
        "timing_tracks": timing_tracks,
        "lit_at_once": {
            "median": float(np.median(counts)),
            "p90": float(np.percentile(counts, 90)),
            "max": int(counts.max()),
        },
        "dark_share": round(float(np.mean(counts == 0)), 2),
        "parent_lit_with_contained": dict(sorted(parent_share.items(), key=lambda kv: (-kv[1], kv[0]))),
        "overlaps_within_layer": _overlaps(elements),
        "elements": rows[:MAX_ELEMENT_ROWS],
        "other_elements": {"count": len(extra), "effects": sum(r["effects"] for r in extra)} if extra else None,
    }
