"""Stem silences bounded by audible hits, and kick times, from the cached analysis."""

from __future__ import annotations

import bisect
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np

from xlights_mcp.audio.drums import KICK_THRESHOLD, SILENCE_THRESHOLD

if TYPE_CHECKING:
    from xlights_mcp.audio.analyzer import SongAnalysis
    from xlights_mcp.audio.stems_model import StemOnsets

Span = tuple[float, float]

BEAT_TOLERANCE_S = 0.1
AUDIBLE_WINDOW_S = (0.03, 0.1)
ROLL_MEDIAN = 3 * SILENCE_THRESHOLD
EXIT_LEVEL = 2 * SILENCE_THRESHOLD
HIT_SNAP_S = 0.1
KICK_SNAP_S = 0.1
DEFAULT_BEAT_S = 0.5


def bounded_silences(
    analysis: SongAnalysis, stem: str, min_ms: int = 1000, merge_gap_ms: int = 0
) -> list[Span]:
    """Silences of a stem: drums bounded by audible hits, sustained stems ending where they return."""
    s = _stem(analysis, stem)
    duration = analysis.duration_seconds
    times = np.asarray(s.energy_times, dtype=float)
    energy = np.asarray(s.energy, dtype=float)
    hits = sorted(set(s.onset_times))
    if stem == "drums":
        spans = _drum_spans(hits, times, energy, analysis.beats.beat_times, duration)
    else:
        spans = _sustained_spans(s.silences, hits, times, energy, duration)
    return _finish(spans, duration, min_ms / 1000, merge_gap_ms / 1000)


def kicks(analysis: SongAnalysis) -> list[float]:
    """Drum hits with a kick's low end (onset_bass >= KICK_THRESHOLD), sorted and unique."""
    drums = _stem(analysis, "drums")
    if len(drums.onset_bass) != len(drums.onset_times):
        raise ValueError(
            "kick levels don't line up with drum onsets; re-run analyze_song with force=true"
        )
    return sorted(
        {t for t, level in zip(drums.onset_times, drums.onset_bass) if level >= KICK_THRESHOLD}
    )


def nearest_kick(
    kick_times: Sequence[float], t: float, window: float = KICK_SNAP_S
) -> float | None:
    i = bisect.bisect_left(kick_times, t)
    near = [
        kick_times[k]
        for k in (i - 1, i)
        if 0 <= k < len(kick_times) and abs(kick_times[k] - t) <= window
    ]
    return min(near, key=lambda k: abs(k - t)) if near else None


def _stem(analysis: SongAnalysis, name: str) -> StemOnsets:
    sa = analysis.stem_analysis
    if not sa.available:
        raise ValueError("stem analysis is unavailable for this song")
    if name not in sa.stems:
        raise ValueError(f"no {name} stem in this analysis")
    return sa.stems[name]


def _audible(t: float, times: np.ndarray, energy: np.ndarray) -> bool:
    if times.size == 0:
        return True
    before, after = AUDIBLE_WINDOW_S
    window = (times >= t - before) & (times <= t + after)
    return bool(window.any() and energy[window].max() >= SILENCE_THRESHOLD)


def _is_roll(start: float, end: float, times: np.ndarray, energy: np.ndarray) -> bool:
    inside = (times >= start) & (times < end)
    return bool(inside.any() and np.median(energy[inside]) >= ROLL_MEDIAN)


def _beat_after(beat_times: Sequence[float]) -> Callable[[float], float]:
    beats = sorted(beat_times)
    period = float(np.median(np.diff(beats))) if len(beats) >= 2 else DEFAULT_BEAT_S

    def after(t: float) -> float:
        if len(beats) >= 2:
            i = bisect.bisect_right(beats, t + BEAT_TOLERANCE_S)
            if i < len(beats):
                return beats[i]
        return t + period

    return after


def _drum_spans(
    hits: list[float],
    times: np.ndarray,
    energy: np.ndarray,
    beat_times: Sequence[float],
    duration: float,
) -> list[Span]:
    audible = [h for h in hits if _audible(h, times, energy)]
    if not audible:
        candidates = [(0.0, duration)]
    else:
        after = _beat_after(beat_times)
        candidates = [
            (0.0, audible[0]),
            *((after(a), b) for a, b in pairwise(audible)),
            (after(audible[-1]), duration),
        ]
    return [(s, e) for s, e in candidates if e > s and not _is_roll(s, e, times, energy)]


def _sustained_spans(
    silences: Sequence[Span],
    hits: list[float],
    times: np.ndarray,
    energy: np.ndarray,
    duration: float,
) -> list[Span]:
    spans = []
    for start, end in silences:
        if times.size == 0:
            spans.append((start, end))
            continue
        back = (times >= end) & (energy >= EXIT_LEVEL)
        if back.any():
            frame = float(times[back][0])
            near = [h for h in hits if abs(h - frame) <= HIT_SNAP_S]
            spans.append((start, min(near, key=lambda h: abs(h - frame)) if near else frame))
        else:
            spans.append((start, duration))
    return spans


def _finish(spans: list[Span], duration: float, min_s: float, merge_gap_s: float) -> list[Span]:
    clamped = sorted((max(0.0, s), min(duration, e)) for s, e in spans)
    kept = [(s, e) for s, e in clamped if e > s and e - s >= min_s]
    merged: list[Span] = []
    for s, e in kept:
        if merged and (s <= merged[-1][1] or s - merged[-1][1] < merge_gap_s):
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged
