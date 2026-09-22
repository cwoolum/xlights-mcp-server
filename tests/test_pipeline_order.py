"""full_analysis feeds the drum stem into beat and structure detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.audio import analyzer
from xlights_mcp.audio.analyzer import StemAnalysis, StemOnsets, full_analysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.separator import StemPaths
from xlights_mcp.config import AudioConfig


def test_drum_stem_reaches_beats_and_structure(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    drums = StemOnsets(name="drums", onset_times=[0.0, 0.5])
    calls: list[tuple[str, object]] = []
    beat_map = BeatMap(tempo=120.0)

    monkeypatch.setattr(analyzer, "separate_stems", lambda _p: StemPaths(available=True))
    monkeypatch.setattr(
        analyzer, "analyze_stems", lambda _s, sr: StemAnalysis(available=True, stems={"drums": drums})
    )

    def fake_beats(path, sr, drums=None):
        calls.append(("beats", drums))
        return beat_map

    def fake_structure(path, sr, drums=None, beats=None):
        calls.append(("structure", (drums, beats)))
        return []

    monkeypatch.setattr(analyzer, "detect_beats", fake_beats)
    monkeypatch.setattr(analyzer, "detect_structure", fake_structure)

    full_analysis(click_track, AudioConfig(cache_dir=tmp_path / "cache"))

    assert calls == [("beats", drums), ("structure", (drums, beat_map))]


def test_without_stems_beats_and_structure_get_none(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    seen = {}
    monkeypatch.setattr(analyzer, "separate_stems", lambda _p: StemPaths(available=False))
    monkeypatch.setattr(
        analyzer, "detect_beats", lambda path, sr, drums=None: seen.setdefault("beats", drums) or BeatMap()
    )
    monkeypatch.setattr(
        analyzer, "detect_structure", lambda path, sr, drums=None, beats=None: seen.setdefault("structure", drums) or []
    )

    full_analysis(click_track, AudioConfig(cache_dir=tmp_path / "cache"))

    assert seen == {"beats": None, "structure": None}
