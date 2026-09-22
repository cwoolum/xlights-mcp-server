"""Tests for snapping the beat grid to drum onsets and re-anchoring bar 1."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from drum_fixtures import make_drum_stem

from xlights_mcp.audio import beats as beats_module
from xlights_mcp.audio.beats import anchor_downbeats, detect_beats, snap_beats


def test_snap_moves_a_late_grid_onto_drum_onsets():
    onsets = np.arange(0, 10, 0.5).tolist()
    late = [t + 0.045 for t in onsets]

    snapped = snap_beats(late, onsets)

    assert snapped == pytest.approx(onsets, abs=1e-3)


def test_snap_leaves_beats_with_no_onset_within_60ms():
    snapped = snap_beats([1.0, 2.0], [1.1, 2.03])

    assert snapped == [1.0, 2.03]


def test_snap_with_no_onsets_returns_grid_unchanged():
    assert snap_beats([1.0, 2.0], []) == [1.0, 2.0]


def test_anchors_become_downbeats_and_count_restarts_at_each():
    beats = np.arange(0, 40, 0.5).tolist()  # 80 beats
    anchors = [beats[10], beats[45]]  # beat 3 and beat 2 of a count from 0

    downbeats = anchor_downbeats(beats, anchors)

    expected_idx = [2, 6] + list(range(10, 45, 4)) + list(range(45, 80, 4))
    assert downbeats == [beats[i] for i in expected_idx]


def test_anchor_nearest_beat_is_used_when_anchor_is_between_beats():
    beats = np.arange(0, 10, 0.5).tolist()

    downbeats = anchor_downbeats(beats, [3.02])

    assert downbeats[0:3] == [1.0, 3.0, 5.0]


@pytest.fixture
def librosa_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _path: None)


def test_detect_beats_without_drums_is_not_drum_aligned(click_track: Path, librosa_only):
    result = detect_beats(click_track)

    assert result.beat_source == "librosa"
    assert result.drum_aligned is False
    assert result.tempo == pytest.approx(120, rel=0.1)


def test_detect_beats_snaps_to_drum_onsets(click_track: Path, librosa_only):
    # librosa places this click track's beats ~10-30 ms late (0.51, 1.02, 1.53, 2.02, 2.53)
    drums = make_drum_stem([(0, 3)], duration=3.0)

    result = detect_beats(click_track, drums=drums)

    assert result.drum_aligned is True
    assert result.beat_times == pytest.approx([0.5, 1.0, 1.5, 2.0, 2.5], abs=1e-6)
    # Drums from the start and no structural gap: no anchor, base every-4th downbeats kept
    assert result.downbeat_times == pytest.approx([0.5, 2.5], abs=1e-6)


def test_isolated_hit_in_a_gap_does_not_reset_bar_phase(click_track: Path, monkeypatch):
    grid = np.arange(0, 40, 0.5).tolist()
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: (grid, list(range(0, 80, 4))))
    monkeypatch.setattr(beats_module.librosa, "get_duration", lambda **_k: 40.0)
    # runs 0-9.5 and 21-39.5; a lone hit at 15.5 (beat 31) sits in the gap
    drums = make_drum_stem([(0, 10), (15.5, 16), (21, 40)], duration=40.0)

    result = detect_beats(click_track, drums=drums)

    # anchor at 21.0 (beat 42, i.e. 42 % 4 == 2) re-phases the whole song
    assert result.downbeat_times == [grid[i] for i in range(2, 80, 4)]
    assert 15.5 not in result.downbeat_times


def test_detect_beats_uses_madmom_grid_when_available(click_track: Path, monkeypatch):
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: ([0.0, 0.5, 1.0, 1.5, 2.0, 2.5], [1, 5]))

    result = detect_beats(click_track)

    assert result.beat_source == "madmom"
    assert result.downbeat_times == [0.5, 2.5]
    assert result.tempo == pytest.approx(120)
