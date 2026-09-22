"""detect_structure picks EDM labelling, stem-annotated fallback, or mixdown-only."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
from drum_fixtures import make_drum_stem

from xlights_mcp.audio import structure
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.audio.stems_model import StemOnsets
from xlights_mcp.audio.structure import detect_structure


def _beats(duration: float) -> BeatMap:
    return BeatMap(
        tempo=120.0,
        beat_times=np.arange(0, duration, 0.5).tolist(),
        downbeat_times=np.arange(0, duration, 2.0).tolist(),
    )


@pytest.fixture
def two_mixdown_sections(monkeypatch: pytest.MonkeyPatch):
    # The 3 s click track yields no sections from the real labeller (all under 1 s),
    # so stub the mixdown path to test the annotation around it.
    monkeypatch.setattr(
        structure,
        "_mixdown_sections",
        lambda *_a, **_k: [
            SongSection(label="verse", start_time=0.0, end_time=1.5),
            SongSection(label="chorus", start_time=1.5, end_time=3.0),
        ],
    )


def test_without_stems_structure_is_mixdown(click_track: Path, two_mixdown_sections):
    sections = detect_structure(click_track)

    assert [s.label for s in sections] == ["verse", "chorus"]
    assert all(s.structure_source == "mixdown" and s.drums is None for s in sections)


def test_steady_drums_fall_back_to_existing_labeller(click_track: Path, two_mixdown_sections):
    drums = make_drum_stem([(0, 3)], duration=3.0)  # one run 0-2.5 s, no mid gap

    sections = detect_structure(click_track, drums=drums, beats=_beats(3.0))

    assert [s.label for s in sections] == ["verse", "chorus"]
    assert all(s.structure_source == "stems" for s in sections)
    # [1.5, 3.0) is 1.0/1.5 covered by the run -> present
    assert [s.drums for s in sections] == ["present", "present"]


def test_drum_stem_without_onsets_marks_every_section_absent(click_track: Path, two_mixdown_sections):
    drums = StemOnsets(name="drums", silences=[(0.0, 3.0)])

    sections = detect_structure(click_track, drums=drums, beats=_beats(3.0))

    assert all(s.structure_source == "stems" and s.drums == "absent" for s in sections)


def test_drum_stem_without_beats_marks_every_section_absent(
    click_track: Path, two_mixdown_sections, caplog: pytest.LogCaptureFixture
):
    # No bar length can be derived without a beat grid, so a drum stem with beats=None
    # can't be split into runs; it must warn and fall back to stems/absent rather than
    # silently behaving like a plain mixdown (structure_source="mixdown").
    drums = make_drum_stem([(0, 3)], duration=3.0)

    with caplog.at_level(logging.WARNING, logger=structure.__name__):
        sections = detect_structure(click_track, drums=drums, beats=None)

    assert all(s.structure_source == "stems" and s.drums == "absent" for s in sections)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_mid_structural_gap_switches_to_edm_labels(click_track: Path, monkeypatch):
    drums = make_drum_stem([(20, 60), (80, 120)], duration=130)
    beats = _beats(130.0)
    edm = [SongSection(label="drop", start_time=0.0, end_time=130.0, structure_source="stems")]
    captured = {}

    def fake_label(runs, gaps, novelty, downbeats, duration, beat_period, energy_at):
        captured["duration"] = duration
        captured["beat_period"] = beat_period
        captured["downbeats"] = downbeats
        captured["novelty"] = novelty
        return edm

    monkeypatch.setattr(structure, "label_edm_sections", fake_label)
    # Duration is mocked because only it drives the drum-gap/EDM math below; the
    # novelty/feature extraction above still runs on the real (3 s) click track.
    monkeypatch.setattr(structure.librosa, "get_duration", lambda **_k: 130.0)

    assert detect_structure(click_track, drums=drums, beats=beats) == edm
    assert captured["duration"] == 130.0
    assert captured["beat_period"] == 0.5
    assert captured["downbeats"] is beats.downbeat_times
    # Real novelty peaks only -- never the _energy_based_segmentation fallback's
    # even split, which would fabricate spurious `build` sections inside a drum gap.
    assert captured["novelty"] and all(0.0 < t < 130.0 for t in captured["novelty"])


def test_short_drum_stop_keeps_the_existing_labeller(click_track: Path, monkeypatch):
    drums = make_drum_stem([(0, 40), (42, 60)], duration=60)  # 2.5 s stop: not structural
    # Duration is mocked because only it drives the drum-gap math below; the
    # novelty/feature extraction still runs on the real (3 s) click track.
    monkeypatch.setattr(structure.librosa, "get_duration", lambda **_k: 60.0)
    # Local monkeypatch (not the shared two_mixdown_sections fixture): the stub section
    # sits entirely inside the 39.5-42 s stop, so it only reads as drum-covered if
    # merge_short_stops folded the stop into one run -- this fails without that merge.
    monkeypatch.setattr(
        structure,
        "_mixdown_sections",
        lambda *_a, **_k: [SongSection(label="verse", start_time=40.0, end_time=41.5)],
    )

    sections = detect_structure(click_track, drums=drums, beats=_beats(60.0))

    assert [s.label for s in sections] == ["verse"]
    assert sections[0].structure_source == "stems"
    assert sections[0].drums == "present"


def test_mixdown_sections_boundary_cleanup_and_dedup():
    """_mixdown_sections inserts a leading 0.0, appends duration, rounds/dedupes
    boundaries and drops sub-1s sections -- independent of the labelling heuristics.
    _label_sections only reads `sections` and `duration`, so rec/features are dummies.
    """
    boundary_times = [3.0, 10.004, 10.001, 10.5, 20.0]
    duration = 25.0

    def energy_at(_start: float, _end: float) -> float:
        return 1.0

    rec = np.zeros((1, 1))
    features = np.zeros((1, 1))

    sections = structure._mixdown_sections(boundary_times, duration, energy_at, rec, features, 22050)

    starts = [s.start_time for s in sections]
    ends = [s.end_time for s in sections]
    assert starts == [0.0, 3.0, 10.5, 20.0]
    assert ends == [3.0, 10.0, 20.0, 25.0]
