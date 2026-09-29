"""Named timing tracks built from the analysis."""

from __future__ import annotations

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.stems_model import StemAnalysis, StemOnsets
from xlights_mcp.sequencer.timing import beat_labels, build_timing_tracks, to_frame


def test_to_frame_rounds_to_the_nearest_frame():
    assert [to_frame(v) for v in (1012, 1013, 1990, 0)] == [1000, 1025, 2000, 0]


def test_beat_labels_restart_at_each_downbeat():
    assert beat_labels([0.0, 0.5, 1.0, 1.5, 2.0, 2.5], [0.0, 2.0]) == ["1", "2", "3", "4", "1", "2"]


def test_a_partial_bar_before_a_reanchored_downbeat_is_short():
    assert beat_labels([0.0, 0.5, 1.0, 1.5, 2.0, 2.5], [0.0, 1.0]) == ["1", "2", "1", "2", "3", "4"]


def test_pickup_beats_count_back_to_four():
    assert beat_labels([0.0, 0.5, 1.0, 1.5], [1.0]) == ["3", "4", "1", "2"]


def test_without_downbeats_beats_count_in_fours():
    assert beat_labels([0.0, 0.5, 1.0, 1.5, 2.0], []) == ["1", "2", "3", "4", "1"]


def test_downbeats_match_beats_within_a_small_tolerance():
    assert beat_labels([0.0, 0.5, 1.0], [0.51]) == ["4", "1", "2"]


def _analysis(stems: bool = False) -> SongAnalysis:
    return SongAnalysis(
        file_path="song.mp3",
        file_name="song.mp3",
        duration_seconds=4.0,
        beats=BeatMap(
            tempo=120.0,
            beat_times=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
            downbeat_times=[0.0, 2.0],
        ),
        stem_analysis=StemAnalysis(
            available=stems,
            stems={"drums": StemOnsets(name="drums", onset_times=[0.51, 1.0, 1.005])} if stems else {},
        ),
    )


def _spans(track) -> list[tuple[str, int, int]]:
    return [(m.label, m.start_time_ms, m.end_time_ms) for m in track.labels[0]]


def test_beats_track_marks_run_to_the_next_beat_and_the_last_to_the_song_end():
    (track,), warnings, errors = build_timing_tracks(["Beats"], _analysis())

    assert track.name == "Beats" and warnings == [] and errors == []
    spans = _spans(track)
    assert [label for label, _, _ in spans] == ["1", "2", "3", "4", "1", "2", "3", "4"]
    assert spans[0] == ("1", 0, 500)
    assert spans[-1] == ("4", 3500, 4000)


def test_bars_track_numbers_the_downbeats():
    (track,), _, _ = build_timing_tracks(["Bars"], _analysis())

    assert _spans(track) == [("1", 0, 2000), ("2", 2000, 4000)]


def test_stem_track_uses_frame_rounded_onsets_and_collapses_same_frame_onsets():
    (track,), _, _ = build_timing_tracks(["Drums"], _analysis(stems=True))

    assert _spans(track) == [("x", 500, 1000), ("x", 1000, 4000)]


def test_stem_track_without_stems_is_skipped_with_a_warning():
    tracks, warnings, errors = build_timing_tracks(["Drums"], _analysis())

    assert tracks == [] and errors == []
    assert "Drums" in warnings[0]


def test_vocals_is_not_a_named_track():
    tracks, _, errors = build_timing_tracks(["Vocals"], _analysis())

    assert tracks == []
    assert "Vocals" in errors[0] and "lyrics" in errors[0]
