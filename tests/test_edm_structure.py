"""Tests for drum-derived (EDM) section labelling."""

from __future__ import annotations

import numpy as np
from drum_fixtures import make_drum_stem

from xlights_mcp.audio.drums import drum_gaps, drum_runs
from xlights_mcp.audio.edm_structure import _merge_short, label_edm_sections

PERIOD = 0.5  # 120 BPM, 2 s bars


def _label(runs_spec, duration, novelty=(), decay_s=0.0):
    stem = make_drum_stem(runs_spec, duration, decay_s=decay_s)
    runs = drum_runs(stem, beat_period=PERIOD, duration=duration)
    gaps = drum_gaps(runs, stem, duration=duration, beat_period=PERIOD)
    downbeats = np.arange(0, duration, 2.0).tolist()
    sections = label_edm_sections(
        runs, gaps, list(novelty), downbeats, duration, PERIOD, energy_at=lambda a, b: 1.0
    )
    return sections


def _summary(sections):
    return [(s.label, s.start_time, s.end_time) for s in sections]


def test_intro_drop_breakdown_drop_outro():
    sections = _label([(20, 60), (80, 120)], 130, decay_s=2.0)

    assert _summary(sections) == [
        ("intro", 0.0, 20.0),
        ("drop", 20.0, 60.0),
        ("breakdown", 60.0, 80.0),
        ("drop", 80.0, 120.0),
        ("outro", 120.0, 130.0),
    ]
    assert sections[2].drums == "decaying"
    assert sections[1].drums == "present"
    assert all(s.structure_source == "stems" and s.confidence == 0.9 for s in sections)


def test_novelty_inside_long_gap_starts_a_build():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[72.0])

    assert [s.label for s in sections] == ["intro", "drop", "breakdown", "build", "drop", "outro"]
    assert sections[3].start_time == 72.0


def test_only_the_last_novelty_boundary_in_a_gap_starts_the_build():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[66.0, 72.0])

    assert [s.label for s in sections] == [
        "intro", "drop", "breakdown", "breakdown", "build", "drop", "outro",
    ]


def test_short_mid_gap_is_a_build_and_drums_from_start_is_intro():
    sections = _label([(0, 40), (48, 80)], 80)

    assert _summary(sections) == [
        ("intro", 0.0, 40.0),
        ("build", 40.0, 48.0),
        ("drop", 48.0, 80.0),
    ]
    assert sections[0].drums == "present"


def test_drums_present_sections_inherit_the_previous_label():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[40.0])

    assert [s.label for s in sections][:3] == ["intro", "drop", "drop"]


def test_novelty_boundary_near_a_drum_boundary_is_dropped():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[21.0])

    assert [s.start_time for s in sections] == [0.0, 20.0, 60.0, 80.0, 120.0]


def test_short_sections_merge_into_predecessor_and_first_into_successor():
    # [0,1) is first, so it merges forward; [5,5.5) then merges back into its predecessor
    assert _merge_short([0.0, 1.0, 5.0, 5.5, 10.0], 2.0) == [0.0, 5.5, 10.0]
    assert _merge_short([0.0, 10.0], 2.0) == [0.0, 10.0]
