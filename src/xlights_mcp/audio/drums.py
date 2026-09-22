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
# Onset low-frequency level at/above this counts as a kick (see onset_bass on StemOnsets).
KICK_THRESHOLD = 0.3
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
    for t, e in zip(times, energy, strict=True):
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


def _require_positive_period(beat_period: float) -> None:
    if not beat_period > 0:
        raise ValueError(f"beat_period must be > 0, got {beat_period}")


def drum_runs(drums: StemOnsets, *, beat_period: float, duration: float) -> list[DrumRun]:
    """Stretches between drum silences that hold at least one bar of onsets.

    A run normally starts at its first onset. EDM drops are often cued in by a
    kickless pickup fill (hi-hat/snare) a beat or two ahead of the downbeat, which
    would otherwise anchor bar 1 too early. When onset_bass is available and the
    stretch opens with such a pickup, the run is trimmed to start at the first
    onset in its first bar that actually is a kick.
    """
    _require_positive_period(beat_period)
    onset_times = np.asarray(drums.onset_times, dtype=float)
    order = np.argsort(onset_times)
    onsets = onset_times[order]
    bass: np.ndarray | None = None
    if len(drums.onset_bass) == len(drums.onset_times):
        bass = np.asarray(drums.onset_bass, dtype=float)[order]

    stretches: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in sorted(drums.silences):
        stretches.append((cursor, start))
        cursor = end
    stretches.append((cursor, duration))

    min_len = BEATS_PER_BAR * beat_period - 1e-6
    runs: list[DrumRun] = []
    for a, b in stretches:
        mask = (onsets >= a - _EDGE_TOLERANCE_S) & (onsets < b + _EDGE_TOLERANCE_S)
        inside = onsets[mask]
        if inside.size == 0:
            continue
        if bass is not None:
            inside_bass = bass[mask]
            first_bar = inside < inside[0] + BEATS_PER_BAR * beat_period
            if inside_bass[0] < KICK_THRESHOLD and np.any(inside_bass[first_bar] >= KICK_THRESHOLD):
                first_kick = int(np.argmax(inside_bass >= KICK_THRESHOLD))
                inside = inside[first_kick:]
        if inside.size and inside[-1] - inside[0] >= min_len:
            runs.append(DrumRun(start=float(inside[0]), end=float(inside[-1])))
    return runs


def drum_gaps(
    runs: list[DrumRun], drums: StemOnsets, *, duration: float, beat_period: float
) -> list[DrumGap]:
    """Leading, between-run and trailing gaps, measured last onset to next first onset."""
    _require_positive_period(beat_period)
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

    gaps: list[DrumGap] = []
    for kind, start, end, prev in spans:
        structural = end - start >= STRUCTURAL_GAP_S
        decaying = structural and prev is not None and _decays(
            prev.end, end, drums.silences, trailing=kind == "trailing"
        )
        gaps.append(
            DrumGap(
                start=start,
                end=end,
                bars=(end - start) / bar,
                kind=kind,
                structural=structural,
                decaying=decaying,
            )
        )
    return gaps


def _decays(
    last_onset: float,
    gap_end: float,
    silences: list[tuple[float, float]],
    *,
    trailing: bool = False,
) -> bool:
    following = [s for s, _ in silences if last_onset - _EDGE_TOLERANCE_S <= s < gap_end]
    if following:
        return min(following) - last_onset > DECAY_S
    # A trailing gap with no recorded silence never cuts cleanly: the stem is
    # still ringing or fading out all the way to the track end.
    return trailing


def merge_short_stops(runs: list[DrumRun], gaps: list[DrumGap]) -> list[DrumRun]:
    """Fold non-structural mid gaps into their neighbours: drums count as present
    through a short stop, per the spec's run/gap distinction."""
    if not runs:
        return []
    mid_gaps = [g for g in gaps if g.kind == "mid"]
    merged = [runs[0]]
    for run, gap in zip(runs[1:], mid_gaps, strict=True):
        if gap.structural:
            merged.append(run)
        else:
            merged[-1] = DrumRun(start=merged[-1].start, end=run.end)
    return merged


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
