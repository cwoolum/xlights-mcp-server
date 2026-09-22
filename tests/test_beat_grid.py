"""Tests for snapping the beat grid to drum onsets and re-anchoring bar 1."""

from __future__ import annotations

import numpy as np
import pytest

from xlights_mcp.audio.beats import anchor_downbeats, snap_beats


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
