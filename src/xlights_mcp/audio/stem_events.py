"""Turn cached stem analysis into compact, windowed payloads for MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from xlights_mcp.audio.analyzer import SongAnalysis

VALID_STEMS = ("drums", "bass", "vocals", "other")
VALID_KINDS = ("onsets", "energy", "silences")
VALID_RESOLUTIONS = ("beat", "bar")
STEMS_UNAVAILABLE = 'Stem analysis unavailable. Install with: uv pip install -e ".[separation]"'


def _ms(t: float) -> int:
    return round(t * 1000)


def stems_summary(analysis: SongAnalysis) -> dict[str, dict] | None:
    sa = analysis.stem_analysis
    if not sa.available:
        return None
    return {
        name: {
            "onsets": len(s.onset_times),
            "mean_energy": round(s.mean_energy, 2),
            "silences_ms": [[_ms(a), _ms(b)] for a, b in s.silences],
        }
        for name, s in sa.stems.items()
    }


def validate_stem_query(stem: str, kind: str, resolution: str, max_events: int = 500) -> str | None:
    if stem not in VALID_STEMS:
        return f"Unknown stem '{stem}'. Valid: {', '.join(VALID_STEMS)}"
    if kind not in VALID_KINDS:
        return f"Unknown kind '{kind}'. Valid: {', '.join(VALID_KINDS)}"
    if resolution not in VALID_RESOLUTIONS:
        return f"Unknown resolution '{resolution}'. Valid: {', '.join(VALID_RESOLUTIONS)}"
    if max_events < 1:
        return "max_events must be >= 1"
    return None


def stem_events(
    analysis: SongAnalysis,
    stem: str,
    kind: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
    max_events: int = 500,
    resolution: str = "beat",
) -> dict[str, Any]:
    error = validate_stem_query(stem, kind, resolution, max_events)
    if error:
        return {"error": error}
    if start_ms is not None and end_ms is not None and start_ms > end_ms:
        return {"error": "start_ms must be <= end_ms"}

    sa = analysis.stem_analysis
    if not sa.available:
        return {"error": STEMS_UNAVAILABLE}
    if stem not in sa.stems:
        return {
            "error": f"Stem '{stem}' was not analyzed for this song. Available: {', '.join(sa.stems)}"
        }

    s = sa.stems[stem]
    lo_ms = start_ms or 0
    hi_ms = end_ms if end_ms is not None else _ms(analysis.duration_seconds)
    base: dict[str, Any] = {"stem": stem, "kind": kind}

    if kind == "onsets":
        events = [_ms(t) for t in s.onset_times if lo_ms <= _ms(t) < hi_ms]
        base["count"] = len(events)
        return _truncate(base, "events_ms", events, max_events, key=lambda e: e)

    if kind == "silences":
        spans_ms = []
        for a, b in s.silences:
            a_ms, b_ms = _ms(a), _ms(b)
            if b_ms > lo_ms and a_ms < hi_ms:
                spans_ms.append([max(a_ms, lo_ms), min(b_ms, hi_ms)])
        base["spans_ms"] = spans_ms
        return base

    grid = analysis.beats.beat_times if resolution == "beat" else analysis.beats.downbeat_times
    if not grid:
        edges = [0.0, analysis.duration_seconds]
    elif grid[0] > 0:
        edges = [0.0, *grid, analysis.duration_seconds]
    else:
        edges = [*grid, analysis.duration_seconds]
    times = np.asarray(s.energy_times, dtype=float)
    energy = np.asarray(s.energy, dtype=float)
    points = []
    for a, b in pairwise(edges):
        a_ms = _ms(a)
        if not lo_ms <= a_ms < hi_ms:
            continue
        mask = (times >= a) & (times < b)
        value = float(energy[mask].mean()) if mask.any() else 0.0
        points.append({"t_ms": a_ms, "energy": round(value, 3)})
    base["resolution"] = resolution
    return _truncate(base, "points", points, max_events, key=lambda p: p["t_ms"])


def _truncate(
    payload: dict[str, Any], field: str, items: list, max_events: int, key: Callable[[Any], int]
) -> dict[str, Any]:
    if len(items) > max_events:
        payload["truncated"] = True
        payload["next_start_ms"] = key(items[max_events])
        items = items[:max_events]
    payload[field] = items
    return payload
