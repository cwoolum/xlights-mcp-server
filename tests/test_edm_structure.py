"""Tests for drum-derived (EDM) section labelling."""

from __future__ import annotations

import numpy as np
from drum_fixtures import make_drum_stem

from xlights_mcp.audio.drums import drum_gaps, drum_runs
from xlights_mcp.audio.edm_structure import _merge_short, label_edm_sections

PERIOD = 0.5  # 120 BPM, 2 s bars


def _label_with_downbeats(
    runs_spec, duration, downbeats, novelty=(), decay_s=0.0, energy_at=lambda a, b: 1.0
):
    stem = make_drum_stem(runs_spec, duration, decay_s=decay_s)
    runs = drum_runs(stem, beat_period=PERIOD, duration=duration)
    gaps = drum_gaps(runs, stem, duration=duration, beat_period=PERIOD)
    return label_edm_sections(
        runs, gaps, list(novelty), list(downbeats), duration, PERIOD, energy_at=energy_at
    )


def _label(runs_spec, duration, novelty=(), decay_s=0.0, energy_at=lambda a, b: 1.0):
    downbeats = np.arange(0, duration, 2.0).tolist()
    return _label_with_downbeats(
        runs_spec, duration, downbeats, novelty=novelty, decay_s=decay_s, energy_at=energy_at
    )


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
    assert sections[0].drums == "absent"  # row 1: leading gap
    assert sections[1].drums == "present"
    assert sections[2].drums == "decaying"
    assert sections[4].drums == "decaying"  # row 2: trailing gap, decaying
    assert all(s.structure_source == "stems" and s.confidence == 0.9 for s in sections)


def test_novelty_inside_long_gap_starts_a_build():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[72.0])

    assert [s.label for s in sections] == ["intro", "drop", "breakdown", "build", "drop", "outro"]
    assert sections[3].start_time == 72.0


def test_only_the_last_novelty_boundary_in_a_gap_starts_the_build():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[66.0, 72.0], decay_s=2.0)

    assert [s.label for s in sections] == [
        "intro", "drop", "breakdown", "breakdown", "build", "drop", "outro",
    ]
    # only the first section of the gap carries the decaying flag
    assert [s.drums for s in sections][2:5] == ["decaying", "absent", "absent"]


def test_short_mid_gap_is_a_build_and_drums_from_start_is_intro():
    sections = _label([(0, 40), (48, 80)], 80)

    assert _summary(sections) == [
        ("intro", 0.0, 40.0),
        ("build", 40.0, 48.0),
        ("drop", 48.0, 80.0),
    ]
    assert sections[0].drums == "present"


def test_short_mid_gap_build_is_decaying_when_the_stem_fades():
    sections = _label([(0, 40), (48, 80)], 80, decay_s=2.0)

    assert _summary(sections) == [
        ("intro", 0.0, 40.0),
        ("build", 40.0, 48.0),
        ("drop", 48.0, 80.0),
    ]
    assert sections[1].drums == "decaying"


def test_drums_present_sections_inherit_the_previous_label():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[40.0])

    assert [s.label for s in sections] == [
        "intro", "drop", "drop", "breakdown", "drop", "outro",
    ]


def test_novelty_boundary_near_a_drum_boundary_is_dropped():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[21.0])

    assert [s.start_time for s in sections] == [0.0, 20.0, 60.0, 80.0, 120.0]


def test_energy_normalises_to_the_peak():
    downbeats = np.arange(0, 130, 2.0).tolist()
    sections = _label_with_downbeats(
        [(20, 60), (80, 120)], 130, downbeats, decay_s=2.0, energy_at=lambda a, b: a
    )

    peak = max(s.start_time for s in sections)
    assert peak > 0
    assert all(s.energy_level == s.start_time / peak for s in sections)
    assert max(s.energy_level for s in sections) == 1.0


def test_energy_all_zero_normalises_to_zero_without_division_error():
    downbeats = np.arange(0, 130, 2.0).tolist()
    sections = _label_with_downbeats(
        [(20, 60), (80, 120)], 130, downbeats, decay_s=2.0, energy_at=lambda a, b: 0.0
    )

    assert all(s.energy_level == 0.0 for s in sections)


def test_empty_downbeats_uses_raw_unsnapped_drum_times():
    sections = _label_with_downbeats([(20, 60), (80, 120)], 130, [], decay_s=2.0)

    assert _summary(sections) == [
        ("intro", 0.0, 20.0),
        ("drop", 20.0, 59.5),  # run 1's last onset, unsnapped
        ("breakdown", 59.5, 80.0),
        ("drop", 80.0, 119.5),  # run 2's last onset, unsnapped
        ("outro", 119.5, 130.0),
    ]


def test_jittered_anchor_after_downbeat_drift_does_not_corrupt_the_second_drop():
    # Regression: downbeats are regular up to 80 s, then drift to 1.98 s bars from
    # the anchor at 80 s (as real re-anchored grids can). A novelty boundary at
    # 82.5 s survives the drum-boundary filter and lands inside the second drop,
    # splitting it in two. Both halves must still read "drop": the anchor at 80 s
    # must not be merged away, and the second half must not inherit the
    # breakdown's label.
    downbeats = [2.0 * i for i in range(41)]  # 0, 2, .., 80
    downbeats += [80.0 + 1.98 * k for k in range(1, 27)]  # jittered bars after 80
    sections = _label_with_downbeats(
        [(20, 60), (80, 120)], 130, downbeats, novelty=[82.5], decay_s=2.0
    )

    assert _summary(sections) == [
        ("intro", 0.0, 20.0),
        ("drop", 20.0, 60.0),
        ("breakdown", 60.0, 80.0),
        ("drop", 80.0, 81.98),
        ("drop", 81.98, 119.6),
        ("outro", 119.6, 130.0),
    ]
    assert sections[3].drums == "present"
    assert sections[4].drums == "present"


def test_anchor_beyond_the_downbeat_grid_does_not_falsely_start_a_drop():
    # The downbeat grid only covers 0-60 s; the second run starts at 100 s, well
    # past it. A naive nearest-downbeat snap would clamp that anchor to 60 s and
    # falsely claim the section from 60 s onward as a "drop", even though drums
    # are still silent there until 100 s. The section should instead fall back
    # to inheriting the preceding drums-present label.
    downbeats = [2.0 * i for i in range(31)]  # 0, 2, .., 60
    sections = _label_with_downbeats([(0, 20), (100, 140)], 140, downbeats)

    assert [s.label for s in sections] == ["intro", "breakdown", "intro"]
    assert [s.start_time for s in sections] == [0.0, 20.0, 60.0]


def test_merge_short_sections_merge_into_predecessor_and_first_into_successor():
    # [0,1) is first, so it merges forward; [5,5.5) then merges back into its predecessor
    assert _merge_short([0.0, 1.0, 5.0, 5.5, 10.0], 2.0) == [0.0, 5.5, 10.0]
    assert _merge_short([0.0, 10.0], 2.0) == [0.0, 10.0]


def test_merge_short_never_deletes_a_protected_point():
    # short section starts at a protected anchor (5.5): merges forward instead,
    # deleting its end boundary rather than the protected anchor.
    assert _merge_short([0.0, 5.0, 5.5, 6.0, 10.0], 2.0, protected={5.5}) == [0.0, 5.5, 10.0]

    # forward merge is itself blocked (end boundary is the final point): the
    # short section is left short rather than corrupting a boundary.
    assert _merge_short([0.0, 5.0, 8.5, 10.0], 2.0, protected={8.5}) == [0.0, 5.0, 8.5, 10.0]

    # forward merge is blocked (end boundary is also protected): both anchors survive.
    assert _merge_short(
        [0.0, 5.0, 8.5, 9.0, 10.0], 2.0, protected={8.5, 9.0}
    ) == [0.0, 5.0, 8.5, 9.0, 10.0]
