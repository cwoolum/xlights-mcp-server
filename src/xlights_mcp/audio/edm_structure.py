"""Section labelling for tracks with a structural mid-song drum gap.

Implements the labels table in docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise

import numpy as np

from xlights_mcp.audio.drums import BEATS_PER_BAR, DrumGap, DrumRun, anchor_starts
from xlights_mcp.audio.sections import SongSection

NOVELTY_MERGE_S = 2.0
BUILD_MAX_BARS = 8
EDM_CONFIDENCE = 0.9


def label_edm_sections(
    runs: list[DrumRun],
    gaps: list[DrumGap],
    novelty_times: list[float],
    downbeat_times: list[float],
    duration: float,
    beat_period: float,
    energy_at: Callable[[float, float], float],
) -> list[SongSection]:
    downbeats = np.asarray(downbeat_times, dtype=float)
    structural = [g for g in gaps if g.structural]

    drum_bounds: list[float] = []
    for g in structural:
        if g.kind != "leading":
            drum_bounds.append(g.start)
        if g.kind != "trailing":
            drum_bounds.append(g.end)
    novelty = [n for n in novelty_times if all(abs(n - d) >= NOVELTY_MERGE_S for d in drum_bounds)]

    inner = sorted({_snap(t, downbeats) for t in drum_bounds + novelty})
    points = [0.0] + [p for p in inner if 0.0 < p < duration] + [float(duration)]
    points = _merge_short(points, BEATS_PER_BAR * beat_period)

    anchors = {_snap(a, downbeats) for a in anchor_starts(gaps)}
    seen_gaps: set[int] = set()
    labelled: list[tuple[str, str, float, float]] = []
    prev_label: str | None = None
    for start, end in pairwise(points):
        mid = (start + end) / 2
        gap = next((g for g in structural if g.start <= mid < g.end), None)
        if gap is not None:
            first_in_gap = id(gap) not in seen_gaps
            seen_gaps.add(id(gap))
            fade = "decaying" if first_in_gap and gap.decaying else "absent"
            label, drums = _gap_label(gap, start, novelty, downbeats, fade)
        elif start in anchors:
            label, drums = "drop", "present"
        elif prev_label is None:
            label, drums = "intro", "present"
        else:
            label, drums = prev_label, "present"
        labelled.append((label, drums, start, end))
        prev_label = label

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
    gap: DrumGap, start: float, novelty: list[float], downbeats: np.ndarray, fade: str
) -> tuple[str, str]:
    if gap.kind == "leading":
        return "intro", "absent"
    if gap.kind == "trailing":
        return "outro", fade
    if gap.bars <= BUILD_MAX_BARS:
        return "build", fade
    inside = [n for n in novelty if gap.start < n < gap.end]
    if inside and start >= _snap(max(inside), downbeats):
        return "build", "absent"
    return "breakdown", fade


def _snap(t: float, downbeats: np.ndarray) -> float:
    if downbeats.size == 0:
        return float(t)
    return float(downbeats[np.argmin(np.abs(downbeats - t))])


def _merge_short(points: list[float], min_len: float) -> list[float]:
    """Drop boundaries until every section is at least min_len long.

    A short section merges into its predecessor; the first section merges into its successor.
    """
    pts = list(points)
    while len(pts) > 2:
        short = next((k for k in range(len(pts) - 1) if pts[k + 1] - pts[k] < min_len - 1e-6), None)
        if short is None:
            break
        del pts[1 if short == 0 else short]
    return pts
