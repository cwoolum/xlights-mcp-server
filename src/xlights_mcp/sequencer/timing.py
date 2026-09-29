"""Frame-grid helpers and the named timing tracks built from a song analysis."""

from __future__ import annotations

import bisect
from collections.abc import Sequence

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.drums import BEATS_PER_BAR
from xlights_mcp.xlights.xsq_writer import TimingTrack, TimingTrackLabel

FRAME_MS = 25
TIMING_TRACK_NAMES = ("Beats", "Bars", "Drums", "Bass", "Instruments")
_STEM_TRACKS = {"Drums": "drums", "Bass": "bass", "Instruments": "other"}
_DOWNBEAT_TOLERANCE_S = 0.05


def to_frame(ms: float, frame_ms: int = FRAME_MS) -> int:
    return int(round(ms / frame_ms)) * frame_ms


def last_frame_ms(duration_ms: int, frame_ms: int = FRAME_MS) -> int:
    return duration_ms - duration_ms % frame_ms


def _on_downbeat(t: float, downbeats: list[float]) -> bool:
    i = bisect.bisect_left(downbeats, t)
    return any(
        abs(t - downbeats[k]) < _DOWNBEAT_TOLERANCE_S for k in (i - 1, i) if 0 <= k < len(downbeats)
    )


def beat_labels(beat_times: Sequence[float], downbeat_times: Sequence[float]) -> list[str]:
    """Each beat's position in its bar: 1 on a downbeat, counting up; pickup beats count back to 4."""
    downbeats = sorted(downbeat_times)
    on_downbeat = [_on_downbeat(t, downbeats) for t in beat_times]
    first = next((i for i, down in enumerate(on_downbeat) if down), None)
    if first is None:
        return [str(i % BEATS_PER_BAR + 1) for i in range(len(beat_times))]
    labels = [str((i - first) % BEATS_PER_BAR + 1) for i in range(first)]
    position = 0
    for down in on_downbeat[first:]:
        position = 1 if down else position + 1
        labels.append(str(position))
    return labels


def _marks(times_s: Sequence[float], labels: Sequence[str], end_ms: int) -> list[TimingTrackLabel]:
    """Frame-rounded marks, each ending where the next starts; the last ends at end_ms."""
    points = sorted(((to_frame(t * 1000), label) for t, label in zip(times_s, labels)), key=lambda p: p[0])
    marks = []
    for k, (start, label) in enumerate(points):
        end = min(points[k + 1][0] if k + 1 < len(points) else end_ms, end_ms)
        if start >= 0 and end > start:
            marks.append(TimingTrackLabel(label=label, start_time_ms=start, end_time_ms=end))
    return marks


def build_timing_tracks(
    names: Sequence[str], analysis: SongAnalysis
) -> tuple[list[TimingTrack], list[str], list[str]]:
    """(tracks, warnings, errors) for the requested named timing tracks."""
    end_ms = last_frame_ms(analysis.duration_ms)
    tracks: list[TimingTrack] = []
    warnings: list[str] = []
    errors: list[str] = []
    for name in names:
        if name == "Beats":
            beats = analysis.beats.beat_times
            marks = _marks(beats, beat_labels(beats, analysis.beats.downbeat_times), end_ms)
        elif name == "Bars":
            bars = analysis.beats.downbeat_times
            marks = _marks(bars, [str(i + 1) for i in range(len(bars))], end_ms)
        elif name in _STEM_TRACKS:
            stem_name = _STEM_TRACKS[name]
            stem = analysis.stem_analysis.stems.get(stem_name) if analysis.stem_analysis.available else None
            if stem is None or not stem.onset_times:
                warnings.append(f"{name} timing track skipped: no {stem_name} stem onsets (needs stem separation)")
                continue
            marks = _marks(stem.onset_times, ["x"] * len(stem.onset_times), end_ms)
        else:
            hint = " (the Vocals track comes from lyrics, not a stem)" if name == "Vocals" else ""
            errors.append(f"unknown timing track {name!r}; choose from {', '.join(TIMING_TRACK_NAMES)}{hint}")
            continue
        tracks.append(TimingTrack(name=name, labels=[marks]))
    return tracks, warnings, errors
