"""Tests for snapping the beat grid to drum onsets and re-anchoring bar 1."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest
from drum_fixtures import make_drum_stem

from xlights_mcp.audio import beats as beats_module
from xlights_mcp.audio.beats import anchor_downbeats, detect_beats, snap_beats
from xlights_mcp.audio.drums import BEATS_PER_BAR


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


def test_anchor_downbeats_with_no_beats_returns_empty_list():
    assert anchor_downbeats([], [1.0]) == []


def test_anchor_downbeats_with_no_anchors_raises():
    with pytest.raises(ValueError, match="anchor_downbeats needs at least one anchor"):
        anchor_downbeats([0.0, 0.5, 1.0], [])


def _install_fake_madmom(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rnn_error: Exception | None = None,
    dbn_result: np.ndarray | None = None,
    dbn_calls: list[dict] | None = None,
) -> None:
    """Install a fake madmom.features.downbeats module tree in sys.modules."""
    if dbn_result is None:
        dbn_result = np.empty((0, 2))

    class FakeRNNDownBeatProcessor:
        def __call__(self, _path: str) -> str:
            if rnn_error is not None:
                raise rnn_error
            return "activations"

    class FakeDBNDownBeatTrackingProcessor:
        def __init__(self, **kwargs):
            if dbn_calls is not None:
                dbn_calls.append(kwargs)

        def __call__(self, _activations: str) -> np.ndarray:
            return dbn_result

    madmom_mod = types.ModuleType("madmom")
    features_mod = types.ModuleType("madmom.features")
    downbeats_mod = types.ModuleType("madmom.features.downbeats")
    downbeats_mod.RNNDownBeatProcessor = FakeRNNDownBeatProcessor
    downbeats_mod.DBNDownBeatTrackingProcessor = FakeDBNDownBeatTrackingProcessor
    features_mod.downbeats = downbeats_mod
    madmom_mod.features = features_mod

    monkeypatch.setitem(sys.modules, "madmom", madmom_mod)
    monkeypatch.setitem(sys.modules, "madmom.features", features_mod)
    monkeypatch.setitem(sys.modules, "madmom.features.downbeats", downbeats_mod)


def test_madmom_grid_returns_beats_and_bar_one_indices(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.undo()  # restore the real _madmom_grid; this test exercises it directly
    calls: list[dict] = []
    _install_fake_madmom(
        monkeypatch,
        dbn_result=np.array([[0.5, 1], [1.0, 2], [1.5, 3], [2.0, 4], [2.5, 1]]),
        dbn_calls=calls,
    )

    result = beats_module._madmom_grid(Path("song.wav"))

    assert result == ([0.5, 1.0, 1.5, 2.0, 2.5], [0, 4])
    assert calls == [{"beats_per_bar": [4], "fps": 100}]


def test_madmom_grid_returns_none_when_rnn_processor_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.undo()  # restore the real _madmom_grid; this test exercises it directly
    _install_fake_madmom(monkeypatch, rnn_error=RuntimeError("boom"))

    assert beats_module._madmom_grid(Path("song.wav")) is None


def test_madmom_grid_returns_none_when_dbn_result_is_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.undo()  # restore the real _madmom_grid; this test exercises it directly
    _install_fake_madmom(monkeypatch, dbn_result=np.empty((0, 2)))

    assert beats_module._madmom_grid(Path("song.wav")) is None


def test_madmom_grid_returns_none_when_madmom_is_not_importable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.undo()  # restore the real _madmom_grid; this test exercises it directly
    monkeypatch.setitem(sys.modules, "madmom.features.downbeats", None)

    assert beats_module._madmom_grid(Path("song.wav")) is None


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


def test_detect_beats_falls_back_to_every_fourth_beat_when_madmom_has_no_bar_one_rows(
    click_track: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.undo()  # restore the real _madmom_grid; drives it via the fake madmom modules
    # No row has bar position 1 -- madmom found beats but never settled on where
    # bar 1 falls. With no drum stem to anchor from either, downbeats must fall
    # back to every 4th beat, the same default librosa uses.
    _install_fake_madmom(
        monkeypatch,
        dbn_result=np.array([[0.5, 2], [1.0, 3], [1.5, 4], [2.0, 2], [2.5, 3]]),
    )

    result = detect_beats(click_track)

    assert result.beat_source == "madmom"
    assert result.beat_times == [0.5, 1.0, 1.5, 2.0, 2.5]
    assert result.downbeat_times == [
        result.beat_times[i] for i in range(0, len(result.beat_times), BEATS_PER_BAR)
    ]


def test_detect_beats_uses_madmom_grid_when_available(click_track: Path, monkeypatch):
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: ([0.0, 0.5, 1.0, 1.5, 2.0, 2.5], [1, 5]))

    result = detect_beats(click_track)

    assert result.beat_source == "madmom"
    assert result.downbeat_times == [0.5, 2.5]
    assert result.tempo == pytest.approx(120)


def test_anchor_dropped_when_beyond_half_a_beat_period_keeps_base_downbeats(
    click_track: Path, monkeypatch
):
    grid = np.arange(0, 10, 0.5).tolist()  # 20 beats, 0-9.5s
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: (grid, list(range(0, 20, 4))))
    monkeypatch.setattr(beats_module.librosa, "get_duration", lambda **_k: 60.0)
    # Drum run 50-60s is far past the (mocked, too-short) beat grid: the only
    # anchor it produces has no nearby beat, so it must be dropped rather than
    # re-anchoring the whole song onto a beat that doesn't exist.
    drums = make_drum_stem([(50, 60)], duration=60.0)

    result = detect_beats(click_track, drums=drums)

    assert result.downbeat_times == [grid[i] for i in range(0, 20, 4)]


def test_pickup_fill_before_a_drop_re_anchors_to_the_first_kick(
    click_track: Path, monkeypatch
):
    grid = np.arange(0, 40, 0.5).tolist()  # 80 beats
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: (grid, list(range(0, 80, 4))))
    monkeypatch.setattr(beats_module.librosa, "get_duration", lambda **_k: 40.0)
    # Run 2's raw start (20.5, beat 41) is a 2-onset hi-hat/snare pickup with no
    # kick; the first kick lands one beat later at 21.5 (beat 43). Bar 1 must
    # re-anchor to the kick, not the pickup.
    n_run1 = len(np.arange(0, 10, 0.5))
    n_run2 = len(np.arange(20.5, 40, 0.5))
    onset_bass = [1.0] * n_run1 + [0.05, 0.05] + [1.0] * (n_run2 - 2)
    drums = make_drum_stem([(0, 10), (20.5, 40)], duration=40.0, onset_bass=onset_bass)

    result = detect_beats(click_track, drums=drums)

    # anchor at 21.5 (beat 43, 43 % 4 == 3) rather than the raw pickup start at
    # 20.5 (beat 41, 41 % 4 == 1).
    assert result.downbeat_times == [grid[i] for i in range(3, 80, 4)]


def test_detect_beats_leading_gap_with_two_anchors_reanchors_whole_song(
    click_track: Path, monkeypatch
):
    grid = np.arange(0, 40, 0.5).tolist()  # 80 beats
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: (grid, list(range(0, 80, 4))))
    monkeypatch.setattr(beats_module.librosa, "get_duration", lambda **_k: 40.0)
    # runs 6.5-19.5 and 26.5-39.5: anchors at 6.5 (beat 13) and 26.5 (beat 53)
    drums = make_drum_stem([(6.5, 20), (26.5, 40)], duration=40.0)

    result = detect_beats(click_track, drums=drums)

    # Backward from anchor 13 (13, 9, 5, 1), forward 13..49, then 53..77.
    expected_idx = [1, 5, 9] + list(range(13, 53, 4)) + list(range(53, 80, 4))
    assert result.downbeat_times == [grid[i] for i in expected_idx]
