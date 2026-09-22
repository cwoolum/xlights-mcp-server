"""Tests for drum-stem silences, runs and gaps."""

from __future__ import annotations

import numpy as np
import pytest
from drum_fixtures import make_drum_stem

from xlights_mcp.audio.drums import (
    anchor_starts,
    drum_gaps,
    drum_runs,
    find_silences,
    has_mid_structural_gap,
    merge_short_stops,
    run_coverage,
)
from xlights_mcp.audio.stems_model import StemOnsets

HOP = 512 / 22050
PERIOD = 0.5


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


def test_drum_runs_span_first_to_last_onset_of_each_stretch():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)

    runs = drum_runs(stem, beat_period=PERIOD, duration=130)

    assert [(r.start, r.end) for r in runs] == [(20.0, 59.5), (80.0, 119.5)]


def test_drum_runs_discard_an_isolated_hit():
    stem = make_drum_stem([(20, 60), (70, 70.5), (80, 120)], duration=130)

    runs = drum_runs(stem, beat_period=PERIOD, duration=130)

    assert [r.start for r in runs] == [20.0, 80.0]


def test_drum_gaps_classify_leading_mid_trailing():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)
    runs = drum_runs(stem, beat_period=PERIOD, duration=130)

    gaps = drum_gaps(runs, stem, duration=130, beat_period=PERIOD)

    assert [g.kind for g in gaps] == ["leading", "mid", "trailing"]
    mid = gaps[1]
    assert (mid.start, mid.end) == (59.5, 80.0)
    assert mid.bars == pytest.approx(20.5 / 2.0)
    assert all(g.structural for g in gaps)


def test_short_drum_stop_is_not_structural():
    stem = make_drum_stem([(0, 40), (42, 60)], duration=60)
    runs = drum_runs(stem, beat_period=PERIOD, duration=60)

    gaps = drum_gaps(runs, stem, duration=60, beat_period=PERIOD)

    assert [g.kind for g in gaps] == ["mid", "trailing"]
    assert gaps[0].structural is False
    assert has_mid_structural_gap(gaps) is False


def test_gap_is_decaying_when_silence_starts_over_a_second_after_last_onset():
    fading = make_drum_stem([(20, 60), (80, 120)], duration=130, decay_s=2.0)
    cutting = make_drum_stem([(20, 60), (80, 120)], duration=130)

    fade_gaps = drum_gaps(
        drum_runs(fading, beat_period=PERIOD, duration=130), fading, duration=130, beat_period=PERIOD
    )
    cut_gaps = drum_gaps(
        drum_runs(cutting, beat_period=PERIOD, duration=130), cutting, duration=130, beat_period=PERIOD
    )

    assert fade_gaps[1].decaying is True
    assert cut_gaps[1].decaying is False
    assert fade_gaps[0].decaying is False  # leading gaps never decay


def test_decaying_is_forced_false_when_gap_is_not_structural():
    # Same shape as the short-stop test, but with a decay tail that *would* make
    # the mid gap look decaying if the structural guard weren't applied.
    stem = make_drum_stem([(0, 40), (42, 60)], duration=60, decay_s=1.0)
    runs = drum_runs(stem, beat_period=PERIOD, duration=60)

    gaps = drum_gaps(runs, stem, duration=60, beat_period=PERIOD)

    mid = gaps[0]
    assert mid.kind == "mid"
    assert mid.structural is False
    assert mid.decaying is False


def test_trailing_gap_without_silence_counts_as_decaying():
    # decay_s=30 never drops the tail below the silence threshold before the
    # track ends, so no silence is ever recorded there: the stem is still
    # ringing/fading out rather than having cut cleanly.
    stem = make_drum_stem([(20, 60)], duration=70, decay_s=30)
    runs = drum_runs(stem, beat_period=PERIOD, duration=70)

    gaps = drum_gaps(runs, stem, duration=70, beat_period=PERIOD)

    trailing = gaps[-1]
    assert trailing.kind == "trailing"
    assert trailing.structural is True
    assert trailing.decaying is True


def test_anchor_starts_are_run_starts_after_structural_gaps():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)
    runs = drum_runs(stem, beat_period=PERIOD, duration=130)
    gaps = drum_gaps(runs, stem, duration=130, beat_period=PERIOD)

    assert anchor_starts(gaps) == [20.0, 80.0]
    assert has_mid_structural_gap(gaps) is True


def test_no_onsets_means_no_runs_and_no_gaps():
    stem = StemOnsets(name="drums", silences=[(0.0, 30.0)])

    runs = drum_runs(stem, beat_period=PERIOD, duration=30)

    assert runs == []
    assert drum_gaps(runs, stem, duration=30, beat_period=PERIOD) == []


def test_run_coverage_is_fraction_of_window_inside_runs():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)
    runs = drum_runs(stem, beat_period=PERIOD, duration=130)

    assert run_coverage(runs, 0, 20) == 0.0
    assert run_coverage(runs, 30, 50) == 1.0
    assert run_coverage(runs, 50, 70) == pytest.approx(9.5 / 20)


def test_merge_short_stops_folds_a_non_structural_gap_into_one_run():
    # A 3.5 s stop between two runs is a short drum stop, not a section break:
    # drums count as present through it.
    stem = make_drum_stem([(0, 11.5), (14.5, 30)], duration=30)
    runs = drum_runs(stem, beat_period=PERIOD, duration=30)
    gaps = drum_gaps(runs, stem, duration=30, beat_period=PERIOD)

    merged = merge_short_stops(runs, gaps)

    assert [(r.start, r.end) for r in merged] == [(0.0, 29.5)]
    assert run_coverage(merged, 10, 16) == 1.0


def test_merge_short_stops_leaves_structural_gaps_alone():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)
    runs = drum_runs(stem, beat_period=PERIOD, duration=130)
    gaps = drum_gaps(runs, stem, duration=130, beat_period=PERIOD)

    merged = merge_short_stops(runs, gaps)

    assert [(r.start, r.end) for r in merged] == [(20.0, 59.5), (80.0, 119.5)]


@pytest.mark.parametrize(
    ("onset_times", "silences", "duration", "expected_runs", "expected_mid_structural"),
    [
        # A run exactly one bar (2.0 s) long is kept, not discarded as too short.
        ([0.0, 2.0], [], 4.0, [(0.0, 2.0)], None),
        # A mid gap of exactly 4.0 s (last onset to first onset) is structural.
        ([0.0, 2.0, 6.0, 8.0], [(2.5, 4.5)], 10.0, [(0.0, 2.0), (6.0, 8.0)], True),
        # An onset deep inside a silence (>= 0.5 s from either edge) belongs to no run.
        ([0.0, 2.0, 3.5, 8.0, 10.0], [(2.5, 7.5)], 12.0, [(0.0, 2.0), (8.0, 10.0)], None),
    ],
)
def test_drum_runs_boundary_cases(
    onset_times, silences, duration, expected_runs, expected_mid_structural
):
    stem = StemOnsets(name="drums", onset_times=onset_times, silences=silences)

    runs = drum_runs(stem, beat_period=PERIOD, duration=duration)

    assert [(r.start, r.end) for r in runs] == expected_runs
    if expected_mid_structural is not None:
        gaps = drum_gaps(runs, stem, duration=duration, beat_period=PERIOD)
        mid_gaps = [g for g in gaps if g.kind == "mid"]
        assert mid_gaps[0].structural is expected_mid_structural
