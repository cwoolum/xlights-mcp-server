"""Hit-bounded stem silences and kick times."""

from __future__ import annotations

import numpy as np
import pytest
from show_fixtures import make_analysis

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.silences import _finish, bounded_silences, kicks, nearest_kick
from xlights_mcp.audio.stems_model import StemAnalysis, StemOnsets

DURATION = 16.0
BEATS = np.arange(0, 16, 0.5).tolist()
DOWNBEATS = np.arange(0, 16, 2.0).tolist()
HITS_AROUND_GAP = [*np.arange(0.0, 4.5, 0.5), *np.arange(12.0, 16.0, 0.5)]


def _energy(segments: list[tuple[float, float, float]], duration: float = DURATION):
    times = np.arange(int(duration * 50)) / 50
    energy = np.zeros_like(times)
    for start, end, level in segments:
        energy[(times >= start) & (times < end)] = level
    return times.tolist(), energy.tolist()


def _stem(
    name: str,
    onsets: list[float],
    segments: list[tuple[float, float, float]] = (),
    silences: list[tuple[float, float]] = (),
    audible: bool = True,
    onset_bass: list[float] | None = None,
) -> StemOnsets:
    hit_segments = [(h, h + 0.08, 0.8) for h in onsets] if audible else []
    times, energy = _energy([*hit_segments, *segments])
    return StemOnsets(
        name=name,
        onset_times=list(onsets),
        onset_bass=onset_bass if onset_bass is not None else [1.0] * len(onsets),
        energy=energy,
        energy_times=times,
        silences=list(silences),
    )


def _analysis(stem: StemOnsets, beats: list[float] = BEATS) -> SongAnalysis:
    return make_analysis(
        DURATION,
        beats,
        DOWNBEATS,
        stem_analysis=StemAnalysis(available=True, stems={stem.name: stem}),
    )


def _drums(onsets, segments=(), beats=BEATS) -> SongAnalysis:
    return _analysis(_stem("drums", list(onsets), segments), beats)


def test_drum_silence_starts_at_the_beat_after_the_last_hit_not_at_the_tail_end():
    analysis = _drums(HITS_AROUND_GAP, [(4.08, 6.0, 0.2)])

    assert bounded_silences(analysis, "drums") == [(4.5, 12.0)]


def test_ghost_onsets_over_bleed_do_not_split_a_drum_silence():
    onsets = sorted([*HITS_AROUND_GAP, 9.0, 10.0])
    segments = [(4.08, 6.0, 0.2), (8, 12, 0.06), (8.9, 9.2, 0.02), (9.9, 10.2, 0.02)]

    assert bounded_silences(_drums(onsets, segments), "drums") == [(4.5, 12.0)]


def test_a_loud_stretch_without_hits_is_a_roll_and_not_silent():
    analysis = _drums(HITS_AROUND_GAP, [(4.08, 6.0, 0.2), (5, 11.9, 0.5)])

    assert bounded_silences(analysis, "drums") == []


def test_a_hit_just_before_a_beat_moves_the_silence_to_the_next_beat():
    onsets = [*np.arange(0.0, 4.0, 0.5), 3.92, *np.arange(12.0, 16.0, 0.5)]

    assert bounded_silences(_drums(sorted(onsets), [(4.0, 6.0, 0.2)]), "drums") == [(4.5, 12.0)]


def test_a_span_past_the_end_of_the_grid_uses_the_beat_period():
    beats = np.arange(0, 10.01, 0.5).tolist()
    onsets = [*np.arange(0.0, 4.5, 0.5), 12.0, 12.5]

    assert bounded_silences(_drums(onsets, beats=beats), "drums") == [(4.5, 12.0), (13.0, 16.0)]


def test_a_grid_with_fewer_than_two_beats_falls_back_to_half_a_second():
    onsets = [*np.arange(0.0, 4.0, 0.5), 3.92, *np.arange(12.0, 16.0, 0.5)]

    assert bounded_silences(_drums(sorted(onsets), beats=[]), "drums") == [
        (pytest.approx(4.42), 12.0)
    ]


def test_an_empty_drum_stem_is_silent_throughout():
    assert bounded_silences(_drums([]), "drums") == [(0.0, 16.0)]


def test_duplicate_onsets_change_nothing():
    onsets = sorted([*HITS_AROUND_GAP, 2.0])

    assert bounded_silences(_drums(onsets, [(4.08, 6.0, 0.2)]), "drums") == [(4.5, 12.0)]


def _bass(silences, segments, onsets=()) -> SongAnalysis:
    return _analysis(_stem("bass", list(onsets), segments, silences, audible=False))


def test_sustained_silence_ends_at_the_hit_where_the_stem_returns_not_at_rumble():
    analysis = _bass([(4.0, 6.0)], [(6.0, 7.5, 0.06), (7.52, 16.0, 0.5)], onsets=[7.55])

    assert bounded_silences(analysis, "bass") == [(4.0, 7.55)]


def test_a_held_note_keeps_the_stored_end():
    analysis = _bass([(4.0, 6.0)], [(6.0, 16.0, 0.4)])

    assert bounded_silences(analysis, "bass") == [(4.0, 6.0)]


def test_a_stem_that_never_returns_runs_to_the_duration():
    analysis = _bass([(4.0, 6.0)], [(6.0, 16.0, 0.07)])

    assert bounded_silences(analysis, "bass") == [(4.0, 16.0)]


def test_silences_bridged_by_a_quiet_stretch_join_into_one_span():
    analysis = _bass([(2.0, 4.0), (4.3, 6.0)], [(4.0, 4.3, 0.07), (6.0, 16.0, 0.5)])

    assert bounded_silences(analysis, "bass") == [(2.0, 6.0)]


def test_hits_inside_a_sustained_silence_do_not_split_it():
    analysis = _bass([(4.0, 6.0)], [(6.0, 16.0, 0.5)], onsets=[5.0])

    assert bounded_silences(analysis, "bass") == [(4.0, 6.0)]


def test_min_ms_filters_before_merge_gap_ms_joins():
    onsets = np.arange(0.0, 16.0, 0.45).tolist()
    analysis = _drums(onsets)

    assert bounded_silences(analysis, "drums", min_ms=1000, merge_gap_ms=500) == []


def test_min_ms_zero_keeps_short_spans():
    onsets = np.arange(0.0, 16.0, 0.45).tolist()

    spans = bounded_silences(_drums(onsets), "drums", min_ms=0)

    assert spans
    assert all(end - start < 1.0 for start, end in spans)


def test_merge_gap_joins_spans_closer_than_the_gap():
    analysis = _bass([(2.0, 4.0), (4.3, 6.0)], [(4.0, 4.3, 0.5), (6.0, 16.0, 0.5)])

    assert bounded_silences(analysis, "bass", merge_gap_ms=0) == [(2.0, 4.0), (4.3, 6.0)]
    assert bounded_silences(analysis, "bass", merge_gap_ms=500) == [(2.0, 6.0)]


def test_finish_merges_touching_spans_and_clamps_to_the_duration():
    assert _finish([(1, 3), (3, 5), (14, 20)], 16, 1, 0) == [(1, 5), (14, 16)]


def test_bounded_silences_needs_the_stem():
    analysis = _drums([])

    with pytest.raises(ValueError, match="no bass stem"):
        bounded_silences(analysis, "bass")


def test_kicks_are_drum_hits_with_a_kick_low_end_sorted_and_unique():
    drums = _stem("drums", [1.0, 2.0, 3.0, 3.0], onset_bass=[0.3, 0.29, 0.9, 0.9])

    assert kicks(_analysis(drums)) == [1.0, 3.0]


def test_kicks_error_without_stems():
    analysis = make_analysis(DURATION, BEATS, DOWNBEATS)

    with pytest.raises(ValueError, match="unavailable"):
        kicks(analysis)


def test_kicks_error_without_a_drums_stem():
    with pytest.raises(ValueError, match="no drums stem"):
        kicks(_analysis(_stem("bass", [1.0])))


def test_kicks_error_when_bass_levels_do_not_line_up():
    drums = _stem("drums", [1.0, 2.0], onset_bass=[1.0])

    with pytest.raises(ValueError, match="analyze_song with force=true"):
        kicks(_analysis(drums))


def test_nearest_kick_within_the_window():
    assert nearest_kick([19.94], 20.0) == 19.94


def test_nearest_kick_outside_the_window_is_none():
    assert nearest_kick([19.85], 20.0) is None


def test_nearest_kick_picks_the_closer_side():
    assert nearest_kick([19.95, 20.04], 20.0) == 20.04


def test_nearest_kick_without_kicks_is_none():
    assert nearest_kick([], 20.0) is None


def test_a_kick_at_zero_is_returned_not_treated_as_missing():
    assert nearest_kick([0.0], 0.03) == 0.0
