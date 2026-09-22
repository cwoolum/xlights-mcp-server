"""Beat and tempo detection for music files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import librosa
import numpy as np
from pydantic import BaseModel, Field

from xlights_mcp.audio.drums import BEATS_PER_BAR, anchor_starts, drum_gaps, drum_runs
from xlights_mcp.audio.stems_model import StemOnsets

logger = logging.getLogger(__name__)


class BeatMap(BaseModel):
    """Beat analysis results for a song."""

    tempo: float = 0.0  # BPM
    beat_times: list[float] = Field(default_factory=list)  # seconds
    downbeat_times: list[float] = Field(default_factory=list)  # bar start times
    onset_times: list[float] = Field(default_factory=list)  # note onset times
    beats_per_bar: int = 4
    beat_source: Literal["madmom", "librosa"] = "librosa"
    drum_aligned: bool = False

    @property
    def beat_times_ms(self) -> list[int]:
        """Beat times in milliseconds (xLights native unit)."""
        return [int(t * 1000) for t in self.beat_times]

    @property
    def downbeat_times_ms(self) -> list[int]:
        """Downbeat times in milliseconds."""
        return [int(t * 1000) for t in self.downbeat_times]

    @property
    def onset_times_ms(self) -> list[int]:
        """Onset times in milliseconds."""
        return [int(t * 1000) for t in self.onset_times]


SNAP_TOLERANCE_S = 0.060


def snap_beats(beats: list[float], onsets: list[float], tol: float = SNAP_TOLERANCE_S) -> list[float]:
    """Move each beat to the nearest onset within tol; beats with none in range stay put."""
    if not onsets:
        return list(beats)
    arr = np.sort(np.asarray(onsets, dtype=float))
    snapped = []
    for b in beats:
        i = int(np.searchsorted(arr, b))
        candidates = arr[max(i - 1, 0) : i + 1]
        nearest = float(candidates[np.argmin(np.abs(candidates - b))])
        snapped.append(nearest if abs(nearest - b) <= tol else b)
    return snapped


def anchor_downbeats(
    beats: list[float], anchors: list[float], beats_per_bar: int = BEATS_PER_BAR
) -> list[float]:
    """Downbeats counted from each anchor's nearest beat until the next anchor.

    Beats before the first anchor are counted backwards from it. The partial bar
    left where one count meets the next anchor is intentional: drops are placed
    against the phrase, not the previous bar count.

    Returns [] when there are no beats. Raises ValueError when there are no
    anchors — callers with no anchors should pass the base downbeats instead.
    """
    if not beats:
        return []
    if not anchors:
        raise ValueError("anchor_downbeats needs at least one anchor")
    grid = np.asarray(beats, dtype=float)
    starts = sorted({int(np.argmin(np.abs(grid - a))) for a in anchors})
    idx = set(range(starts[0], -1, -beats_per_bar))
    for k, start in enumerate(starts):
        stop = starts[k + 1] if k + 1 < len(starts) else len(beats)
        idx.update(range(start, stop, beats_per_bar))
    return [beats[i] for i in sorted(idx)]


def detect_beats(audio_path: Path, sr: int = 22050, drums: StemOnsets | None = None) -> BeatMap:
    """Detect beats, downbeats and mixdown onsets.

    Base grid from madmom when installed, else librosa. With a drum stem the grid
    is snapped to drum onsets and bar 1 is re-anchored at each run that follows a
    structural drum gap (see docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md).
    """
    logger.info(f"Analyzing beats: {audio_path}")
    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr).tolist()

    grid = _madmom_grid(audio_path)
    if grid is not None:
        beat_times, downbeat_idx = grid
        beat_source = "madmom"
    else:
        _, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        downbeat_idx = list(range(0, len(beat_times), BEATS_PER_BAR))
        beat_source = "librosa"

    tempo = 60.0 / float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 0.0

    drum_aligned = False
    if drums is not None and drums.onset_times and beat_times:
        beat_times = snap_beats(beat_times, drums.onset_times)
        drum_aligned = True
    downbeat_times = [beat_times[i] for i in downbeat_idx]

    if drum_aligned and tempo > 0:
        period = 60.0 / tempo
        runs = drum_runs(drums, beat_period=period, duration=duration)
        anchors = anchor_starts(drum_gaps(runs, drums, duration=duration, beat_period=period))
        grid_arr = np.asarray(beat_times, dtype=float)
        valid_anchors = [a for a in anchors if np.min(np.abs(grid_arr - a)) <= period / 2]
        dropped = len(anchors) - len(valid_anchors)
        if dropped:
            logger.info(
                f"Dropped {dropped} anchor(s) more than half a beat period from the nearest beat"
            )
        if valid_anchors:
            downbeat_times = anchor_downbeats(beat_times, valid_anchors)
    elif drum_aligned:
        logger.debug("drum_aligned but tempo is 0; skipping downbeat re-anchoring")

    logger.info(
        f"Detected: tempo={tempo:.1f} BPM ({beat_source}), {len(beat_times)} beats, "
        f"{len(downbeat_times)} downbeats, {len(onset_times)} onsets, drum_aligned={drum_aligned}"
    )
    return BeatMap(
        tempo=tempo,
        beat_times=beat_times,
        downbeat_times=downbeat_times,
        onset_times=onset_times,
        beat_source=beat_source,
        drum_aligned=drum_aligned,
    )


def _madmom_grid(audio_path: Path) -> tuple[list[float], list[int]] | None:
    """Beat times and indices of madmom's bar-position-1 beats, or None if unavailable."""
    try:
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor
    except ImportError:
        logger.debug("madmom not installed, using librosa beat tracking")
        return None
    try:
        activations = RNNDownBeatProcessor()(str(audio_path))
        rows = DBNDownBeatTrackingProcessor(beats_per_bar=[BEATS_PER_BAR], fps=100)(activations)
    except Exception as e:  # noqa: BLE001 - any madmom failure falls back to librosa
        logger.warning(f"madmom beat tracking failed, using librosa: {e}")
        return None
    if len(rows) == 0:
        return None
    return [float(r[0]) for r in rows], [i for i, r in enumerate(rows) if int(r[1]) == 1]
