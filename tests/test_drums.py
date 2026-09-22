"""Tests for drum-stem silences, runs and gaps."""

from __future__ import annotations

import numpy as np
import pytest

from xlights_mcp.audio.drums import find_silences

HOP = 512 / 22050


def _curve(duration: float, quiet: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    times = np.arange(0, duration, HOP)
    energy = np.ones_like(times)
    for a, b in quiet:
        energy[(times >= a) & (times < b)] = 0.0
    return energy, times


def test_find_silences_detects_a_three_second_gap():
    energy, times = _curve(10.0, [(4.0, 7.0)])

    spans = find_silences(energy, times, end=10.0)

    assert len(spans) == 1
    start, end = spans[0]
    assert start == pytest.approx(4.0, abs=HOP)
    assert end == pytest.approx(7.0, abs=HOP)


def test_find_silences_ignores_dips_shorter_than_one_second():
    energy, times = _curve(10.0, [(4.0, 4.5)])

    assert find_silences(energy, times, end=10.0) == []


def test_find_silences_closes_a_silence_running_to_the_end():
    energy, times = _curve(10.0, [(8.0, 10.0)])

    spans = find_silences(energy, times, end=10.0)

    assert spans == [(pytest.approx(8.0, abs=HOP), 10.0)]
