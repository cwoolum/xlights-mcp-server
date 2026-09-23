"""Section labelling for tracks with a structural mid-song drum gap.

Implements the labels table in docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from itertools import pairwise

import numpy as np

from xlights_mcp.audio.drums import BEATS_PER_BAR, DrumGap, anchor_starts
from xlights_mcp.audio.sections import SongSection

NOVELTY_MERGE_S = 2.0
BUILD_MAX_BARS = 8
# Measured last-hit-to-first-kick, an N-bar riser naturally runs up to a beat over.
BUILD_SLACK_BARS = 0.5
EDM_CONFIDENCE = 0.9


def label_edm_sections(
    gaps: list[DrumGap],
    novelty_times: list[float],
    downbeat_times: list[float],
    duration: float,
    beat_period: float,
    energy_at: Callable[[float, float], float],
    anchor_times: list[float] | None = None,
) -> list[SongSection]:
    """Label sections from drum gaps.

    anchor_times are the drop starts the beat grid was re-anchored to
    (BeatMap.anchor_times); when omitted they are derived from the gaps.
    """
    downbeats = np.asarray(downbeat_times, dtype=float)
    structural = [g for g in gaps if g.structural]
    max_dist = 2 * beat_period  # half a bar: snapping this far is no longer "nearby"

    drum_bounds: list[float] = []
    snapped_bounds: list[float] = []
    # A gap shorter than the snapping distance can have both edges snap to the
    # same downbeat and vanish; such a gap keeps its raw edges.
    unsnapped_ends: dict[float, float] = {}
    for g in structural:
        start = _snap(g.start, downbeats, max_dist) if g.kind != "leading" else None
        end = _snap(g.end, downbeats, max_dist) if g.kind != "trailing" else None
        if start is not None and end is not None and _close(start, end):
            unsnapped_ends[end] = g.end
            start, end = g.start, g.end
        if start is not None:
            drum_bounds.append(g.start)
            snapped_bounds.append(start)
        if end is not None:
            drum_bounds.append(g.end)
            snapped_bounds.append(end)
    novelty = [n for n in novelty_times if all(abs(n - d) >= NOVELTY_MERGE_S for d in drum_bounds)]

    inner = sorted({*snapped_bounds, *(_snap(t, downbeats, max_dist) for t in novelty)})
    points = [0.0] + [p for p in inner if 0.0 < p < duration] + [float(duration)]

    if anchor_times is None:
        anchor_times = anchor_starts(gaps)
    anchors = set()
    for a in anchor_times:
        snapped = _snap(a, downbeats, max_dist)
        collapsed = next((raw for s, raw in unsnapped_ends.items() if _close(s, snapped)), None)
        anchors.add(collapsed if collapsed is not None else snapped)
    min_len = (BEATS_PER_BAR - 0.5) * beat_period
    points = _merge_short(points, min_len, protected=anchors)

    seen_gaps: set[int] = set()
    labelled: list[tuple[str, str, float, float]] = []
    prev_present_label: str | None = None
    for idx, (start, end) in enumerate(pairwise(points)):
        mid = (start + end) / 2
        gap = next((g for g in structural if g.start <= mid < g.end), None)
        if gap is not None:
            first_in_gap = id(gap) not in seen_gaps
            seen_gaps.add(id(gap))
            fade = "decaying" if first_in_gap and gap.decaying else "absent"
            label, drums = _gap_label(gap, start, novelty, downbeats, max_dist, fade)
        elif _is_anchor(start, anchors):
            label, drums = "drop", "present"
        elif idx == 0:
            label, drums = "intro", "present"
        else:
            label, drums = prev_present_label or "drop", "present"
        if drums == "present":
            prev_present_label = label
        labelled.append((label, drums, start, end))

    energies = [energy_at(s, e) for _, _, s, e in labelled]
    peak = max(energies, default=0.0) or 1.0
    return [
        SongSection(
            label=label,
            start_time=start,
            end_time=end,
            energy_level=energy / peak,
            confidence=EDM_CONFIDENCE,
            structure_source="stems",
            drums=drums,
        )
        for (label, drums, start, end), energy in zip(labelled, energies)
    ]


def _gap_label(
    gap: DrumGap,
    start: float,
    novelty: list[float],
    downbeats: np.ndarray,
    max_dist: float,
    fade: str,
) -> tuple[str, str]:
    if gap.kind == "leading":
        return "intro", "absent"
    if gap.kind == "trailing":
        return "outro", fade
    if gap.bars <= BUILD_MAX_BARS + BUILD_SLACK_BARS:
        return "build", fade
    inside = [n for n in novelty if gap.start < n < gap.end]
    if inside and start >= _snap(max(inside), downbeats, max_dist):
        return "build", "absent"
    return "breakdown", fade


def _close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


def _snap(t: float, downbeats: np.ndarray, max_dist: float) -> float:
    """The nearest downbeat, but only if it is actually nearby.

    A boundary the downbeat grid doesn't reach (nearest downbeat farther than
    max_dist) keeps its raw time rather than being clamped to a distant downbeat.
    """
    if downbeats.size == 0:
        return float(t)
    idx = np.argmin(np.abs(downbeats - t))
    nearest = float(downbeats[idx])
    return nearest if abs(nearest - t) <= max_dist else float(t)


def _is_anchor(t: float, anchors: set[float]) -> bool:
    return any(_close(t, a) for a in anchors)


def _merge_short(
    points: list[float], min_len: float, protected: set[float] | None = None
) -> list[float]:
    """Drop boundaries until every section is at least min_len long.

    A short section normally merges into its predecessor (its start boundary is
    deleted). The first section instead merges into its successor (its end
    boundary is deleted). A point in `protected` — a snapped drop anchor — is
    never deleted: a short section starting at a protected point merges forward
    instead, unless its end boundary is also protected or is the final point, in
    which case the section is left short rather than dropping a real boundary.
    """
    protected = protected or set()

    def has_close(value: float, collection: Iterable[float]) -> bool:
        return any(_close(value, q) for q in collection)

    pts = list(points)
    unmergeable: list[float] = []
    while len(pts) > 2:
        short = next(
            (
                k
                for k in range(len(pts) - 1)
                if pts[k + 1] - pts[k] < min_len - 1e-6 and not has_close(pts[k], unmergeable)
            ),
            None,
        )
        if short is None:
            break
        start = pts[short]
        if short == 0 or has_close(start, protected):
            end_idx = short + 1
            if end_idx == len(pts) - 1 or has_close(pts[end_idx], protected):
                unmergeable.append(start)
                continue
            del pts[end_idx]
        else:
            del pts[short]
    return pts
