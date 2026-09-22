"""Drum-stem runs and gaps: the shared primitive behind beat re-anchoring and EDM structure.

See docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md, "Drum runs and gaps".
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

import numpy as np
from pydantic import BaseModel

from xlights_mcp.audio.stems_model import StemOnsets

SILENCE_THRESHOLD = 0.05
MIN_SILENCE_S = 1.0
STRUCTURAL_GAP_S = 4.0
DECAY_S = 1.0
BEATS_PER_BAR = 4
# Backtracked onsets can land a few frames before the energy crosses the threshold.
_EDGE_TOLERANCE_S = 0.1


def find_silences(
    energy: np.ndarray,
    times: np.ndarray,
    end: float,
    threshold: float = SILENCE_THRESHOLD,
    min_len: float = MIN_SILENCE_S,
) -> list[tuple[float, float]]:
    """Spans where normalised energy stays below threshold for at least min_len seconds."""
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for t, e in zip(times, energy):
        if e < threshold:
            if start is None:
                start = float(t)
        elif start is not None:
            if t - start >= min_len:
                spans.append((start, float(t)))
            start = None
    if start is not None and end - start >= min_len:
        spans.append((start, float(end)))
    return spans


class DrumRun(BaseModel):
    start: float  # first onset, seconds
    end: float  # last onset, seconds


class DrumGap(BaseModel):
    start: float
    end: float
    bars: float
    kind: Literal["leading", "mid", "trailing"]
    structural: bool
    decaying: bool


def drum_runs(drums: StemOnsets, beat_period: float, duration: float) -> list[DrumRun]:
    """Stretches between drum silences that hold at least one bar of onsets."""
    onsets = np.sort(np.asarray(drums.onset_times, dtype=float))
    stretches: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in sorted(drums.silences):
        stretches.append((cursor, start))
        cursor = end
    stretches.append((cursor, duration))

    min_len = BEATS_PER_BAR * beat_period - 1e-6
    runs: list[DrumRun] = []
    for a, b in stretches:
        inside = onsets[(onsets >= a - _EDGE_TOLERANCE_S) & (onsets < b + _EDGE_TOLERANCE_S)]
        if inside.size and inside[-1] - inside[0] >= min_len:
            runs.append(DrumRun(start=float(inside[0]), end=float(inside[-1])))
    return runs


def drum_gaps(
    runs: list[DrumRun], drums: StemOnsets, duration: float, beat_period: float
) -> list[DrumGap]:
    """Leading, between-run and trailing gaps, measured last onset to next first onset."""
    if not runs:
        return []
    bar = BEATS_PER_BAR * beat_period
    spans: list[tuple[str, float, float, DrumRun | None]] = []
    if runs[0].start > 0:
        spans.append(("leading", 0.0, runs[0].start, None))
    for prev, nxt in pairwise(runs):
        spans.append(("mid", prev.end, nxt.start, prev))
    if runs[-1].end < duration:
        spans.append(("trailing", runs[-1].end, duration, runs[-1]))

    return [
        DrumGap(
            start=start,
            end=end,
            bars=(end - start) / bar,
            kind=kind,
            structural=end - start >= STRUCTURAL_GAP_S,
            decaying=prev is not None and _decays(prev.end, end, drums.silences),
        )
        for kind, start, end, prev in spans
    ]


def _decays(last_onset: float, gap_end: float, silences: list[tuple[float, float]]) -> bool:
    following = [s for s, _ in silences if last_onset - _EDGE_TOLERANCE_S <= s < gap_end]
    return bool(following) and min(following) - last_onset > DECAY_S


def anchor_starts(gaps: list[DrumGap]) -> list[float]:
    """Run starts that follow a structural gap: where bar 1 is re-anchored."""
    return [g.end for g in gaps if g.structural and g.kind != "trailing"]


def has_mid_structural_gap(gaps: list[DrumGap]) -> bool:
    return any(g.kind == "mid" and g.structural for g in gaps)


def run_coverage(runs: list[DrumRun], start: float, end: float) -> float:
    """Fraction of [start, end) covered by drum runs."""
    if end <= start:
        return 0.0
    covered = sum(max(0.0, min(end, r.end) - max(start, r.start)) for r in runs)
    return covered / (end - start)
