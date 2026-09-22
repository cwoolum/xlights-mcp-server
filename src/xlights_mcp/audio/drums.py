"""Drum-stem runs and gaps: the shared primitive behind beat re-anchoring and EDM structure.

See docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md, "Drum runs and gaps".
"""

from __future__ import annotations

import numpy as np

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
