"""Tests for LLM-sized stem payloads."""

from __future__ import annotations

import numpy as np
import pytest
from drum_fixtures import make_drum_stem

from xlights_mcp.audio.analyzer import SongAnalysis, StemAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.stem_events import stem_events, stems_summary, validate_stem_query


@pytest.fixture
def analysis() -> SongAnalysis:
    return SongAnalysis(
        file_path="song.mp3",
        file_name="song.mp3",
        duration_seconds=20.0,
        beats=BeatMap(
            tempo=120.0,
            beat_times=np.arange(0, 20, 0.5).tolist(),
            downbeat_times=np.arange(0, 20, 2.0).tolist(),
        ),
        stem_analysis=StemAnalysis(
            available=True, stems={"drums": make_drum_stem([(0, 8), (12, 20)], duration=20.0)}
        ),
    )


def test_summary_reports_counts_energy_and_silences_in_ms(analysis):
    summary = stems_summary(analysis)

    drums = summary["drums"]
    assert drums["onsets"] == 32
    assert isinstance(drums["mean_energy"], float)
    assert len(drums["silences_ms"]) == 1
    start, end = drums["silences_ms"][0]
    assert isinstance(start, int) and 7700 < start < 7900 and 11900 < end < 12100


def test_summary_is_none_without_stems(analysis):
    analysis.stem_analysis = StemAnalysis()

    assert stems_summary(analysis) is None


def test_onsets_are_windowed_ms(analysis):
    payload = stem_events(analysis, "drums", "onsets", start_ms=1000, end_ms=3000)

    assert payload["events_ms"] == [1000, 1500, 2000, 2500]
    assert payload["count"] == 4
    assert "truncated" not in payload


def test_onsets_truncate_with_resume_point(analysis):
    payload = stem_events(analysis, "drums", "onsets", max_events=3)

    assert payload["events_ms"] == [0, 500, 1000]
    assert payload["truncated"] is True
    assert payload["next_start_ms"] == 1500


def test_energy_one_point_per_beat_in_window(analysis):
    payload = stem_events(analysis, "drums", "energy", start_ms=0, end_ms=4000)

    assert [p["t_ms"] for p in payload["points"]] == list(range(0, 4000, 500))
    assert all(p["energy"] == pytest.approx(1.0, abs=0.01) for p in payload["points"])


def test_energy_bar_resolution_and_truncation(analysis):
    payload = stem_events(analysis, "drums", "energy", resolution="bar", max_events=2)

    assert [p["t_ms"] for p in payload["points"]] == [0, 2000]
    assert payload["next_start_ms"] == 4000


def test_silences_are_clipped_to_window(analysis):
    payload = stem_events(analysis, "drums", "silences", start_ms=10000)

    start, end = payload["spans_ms"][0]
    assert start == 10000
    assert 11900 < end < 12100


def test_energy_near_zero_during_drum_gap(analysis):
    payload = stem_events(analysis, "drums", "energy", start_ms=8000, end_ms=12000)

    assert payload["points"]
    assert all(p["energy"] < 0.05 for p in payload["points"])


def test_onsets_paging_covers_all_events_on_hop_grid(analysis):
    """Regression: raw-second window checks against rounded-ms next_start_ms
    could skip items at page boundaries. Filtering must stay in int-ms space."""
    from drum_fixtures import HOP

    onset_times = [i * HOP for i in range(39)]
    analysis.stem_analysis.stems["drums"].onset_times = onset_times

    all_events: list[int] = []
    start = 0
    while True:
        payload = stem_events(analysis, "drums", "onsets", start_ms=start, max_events=5)
        all_events.extend(payload["events_ms"])
        if not payload.get("truncated"):
            break
        start = payload["next_start_ms"]

    unpaged = stem_events(analysis, "drums", "onsets", max_events=1000)
    assert all_events == unpaged["events_ms"]
    assert len(unpaged["events_ms"]) == 39


def test_missing_specific_stem_lists_available_stems(analysis):
    payload = stem_events(analysis, "bass", "onsets")

    assert payload["error"] == "Stem 'bass' was not analyzed for this song. Available: drums"


@pytest.mark.parametrize("max_events", [0, -1])
def test_max_events_must_be_positive(analysis, max_events):
    payload = stem_events(analysis, "drums", "onsets", max_events=max_events)

    assert payload["error"] == "max_events must be >= 1"


@pytest.mark.parametrize("max_events", [0, -1])
def test_validate_stem_query_rejects_non_positive_max_events(max_events):
    assert validate_stem_query("drums", "onsets", "beat", max_events) == "max_events must be >= 1"


def test_validate_stem_query_default_max_events_keeps_three_arg_call_valid():
    assert validate_stem_query("drums", "onsets", "beat") is None


def test_start_after_end_errors(analysis):
    payload = stem_events(analysis, "drums", "onsets", start_ms=3000, end_ms=1000)

    assert payload["error"] == "start_ms must be <= end_ms"


def test_energy_leading_span_when_grid_starts_late(analysis):
    analysis.beats.beat_times = [4.0, 8.0, 12.0, 16.0]

    payload = stem_events(analysis, "drums", "energy")

    assert payload["points"][0]["t_ms"] == 0


def test_energy_empty_grid_returns_single_span(analysis):
    analysis.beats.beat_times = []
    expected = round(analysis.stem_analysis.stems["drums"].mean_energy, 3)

    payload = stem_events(analysis, "drums", "energy")

    assert payload["points"] == [{"t_ms": 0, "energy": expected}]


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (("kick", "onsets"), "drums"),
        (("drums", "hits"), "onsets"),
    ],
)
def test_invalid_stem_or_kind_lists_valid_values(analysis, args, needle):
    assert needle in stem_events(analysis, *args)["error"]


def test_invalid_resolution_errors(analysis):
    assert "beat" in stem_events(analysis, "drums", "energy", resolution="frame")["error"]


def test_missing_stems_errors_with_install_hint(analysis):
    analysis.stem_analysis = StemAnalysis()

    assert "separation" in stem_events(analysis, "drums", "onsets")["error"]
