"""detect_structure picks EDM labelling, stem-annotated fallback, or mixdown-only."""

from __future__ import annotations

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


def test_mid_structural_gap_switches_to_edm_labels(click_track: Path, monkeypatch):
    drums = make_drum_stem([(20, 60), (80, 120)], duration=130)
    edm = [SongSection(label="drop", start_time=0.0, end_time=130.0, structure_source="stems")]
    captured = {}

    def fake_label(runs, gaps, novelty, downbeats, duration, beat_period, energy_at):
        captured["duration"] = duration
        return edm

    monkeypatch.setattr(structure, "label_edm_sections", fake_label)
    monkeypatch.setattr(structure.librosa, "get_duration", lambda **_k: 130.0)

    assert detect_structure(click_track, drums=drums, beats=_beats(130.0)) == edm
    assert captured["duration"] == 130.0


def test_short_drum_stop_keeps_the_existing_labeller(click_track: Path, two_mixdown_sections, monkeypatch):
    drums = make_drum_stem([(0, 40), (42, 60)], duration=60)  # 2.5 s stop: not structural
    monkeypatch.setattr(structure.librosa, "get_duration", lambda **_k: 60.0)

    sections = detect_structure(click_track, drums=drums, beats=_beats(60.0))

    assert [s.label for s in sections] == ["verse", "chorus"]
    assert all(s.structure_source == "stems" for s in sections)
