"""Cross-module invariant: a `drop` section's start always lands on a real
downbeat, and specifically on the first kick after the preceding drum gap --
never on a kickless pickup fill or a grid phase madmom guessed before the
drums were consulted.

Exercises the real detect_beats (pickup-fill re-anchoring, see beats.py) and
the real detect_structure/label_edm_sections (EDM section labelling, see
structure.py/edm_structure.py) together, rather than each in isolation --
what beats.py re-anchors is exactly what edm_structure.py must place a drop on.
"""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import pytest
from drum_fixtures import make_drum_stem

from xlights_mcp.audio import beats as beats_module
from xlights_mcp.audio.beats import detect_beats
from xlights_mcp.audio.structure import detect_structure


def test_drop_start_times_are_downbeats_at_the_first_kick_after_the_gap(
    click_track: Path, monkeypatch: pytest.MonkeyPatch
):
    grid = np.arange(0, 40, 0.5).tolist()  # 80 beats, 0.5 s apart
    # madmom's own bar-1 phase (every 4th beat from 0) does not match where the
    # drums actually land after the gap -- re-anchoring must override it.
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: (grid, list(range(0, 80, 4))))
    monkeypatch.setattr(librosa, "get_duration", lambda **_k: 40.0)

    # Run 2 opens with a 2-onset kickless pickup fill at 20.5/21.0; the first
    # real kick lands one beat later, at 21.5.
    n_run1 = len(np.arange(0, 10, 0.5))
    n_run2 = len(np.arange(20.5, 40, 0.5))
    onset_bass = [1.0] * n_run1 + [0.05, 0.05] + [1.0] * (n_run2 - 2)
    drums = make_drum_stem([(0, 10), (20.5, 40)], duration=40.0, onset_bass=onset_bass)

    beat_map = detect_beats(click_track, drums=drums)
    sections = detect_structure(click_track, drums=drums, beats=beat_map)

    drops = [s for s in sections if s.label == "drop"]
    assert drops, "expected at least one drop section"
    for drop in drops:
        assert drop.start_time in beat_map.downbeat_times
        assert drop.start_time == 21.5  # first kick after the gap, not the 20.5 pickup
