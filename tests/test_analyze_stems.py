"""Tests for per-stem silence detection in analyze_stems."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from xlights_mcp.audio.analyzer import analyze_stems
from xlights_mcp.audio.separator import StemPaths


def _clicky_drum_stem(path: Path) -> None:
    """6s mono wav @ 22050Hz: clicks every 0.5s from 0-2s and 4.5-6s, silence between."""
    sr = 22050
    duration = 6.0
    y = np.zeros(int(sr * duration), dtype=np.float32)
    click_starts = [0.0, 0.5, 1.0, 1.5, 2.0, 4.5, 5.0, 5.5]
    for beat in click_starts:
        start = int(beat * sr)
        y[start : start + 500] = np.sin(np.linspace(0, 200 * np.pi, 500)).astype(np.float32)
    sf.write(path, y, sr)


def test_analyze_stems_records_drum_silence(tmp_path: Path):
    drum_path = tmp_path / "drums.wav"
    _clicky_drum_stem(drum_path)

    stems = StemPaths(available=True, drums=str(drum_path))
    result = analyze_stems(stems, sr=22050)

    silences = result.stems["drums"].silences
    assert len(silences) == 1
    start, end = silences[0]
    assert 2.0 <= start <= 2.5
    assert 4.3 <= end <= 4.6


def _mixed_bass_and_click_stem(path: Path) -> None:
    """8s mono wav @ 22050Hz: 200ms 60Hz sine bursts at 0/1/2s (kick-like low end),
    short 5kHz clicks at 4/5/6s (no low end), silence between."""
    sr = 22050
    duration = 8.0
    y = np.zeros(int(sr * duration), dtype=np.float32)
    burst_len = int(0.2 * sr)
    tt_burst = np.arange(burst_len) / sr
    for beat in [0.0, 1.0, 2.0]:
        start = int(beat * sr)
        y[start : start + burst_len] += (0.9 * np.sin(2 * np.pi * 60 * tt_burst)).astype(
            np.float32
        )
    click_len = 500
    tt_click = np.arange(click_len) / sr
    for beat in [4.0, 5.0, 6.0]:
        start = int(beat * sr)
        y[start : start + click_len] += (0.9 * np.sin(2 * np.pi * 5000 * tt_click)).astype(
            np.float32
        )
    sf.write(path, y, sr)


def test_analyze_stems_onset_bass_separates_kicks_from_high_clicks(tmp_path: Path):
    drum_path = tmp_path / "drums.wav"
    _mixed_bass_and_click_stem(drum_path)

    stems = StemPaths(available=True, drums=str(drum_path))
    result = analyze_stems(stems, sr=22050)

    onsets = result.stems["drums"].onset_times
    bass = result.stems["drums"].onset_bass
    assert len(bass) == len(onsets)
    assert len(onsets) >= 6  # at least one onset detected per burst/click

    low_freq_onsets = [b for t, b in zip(onsets, bass, strict=True) if t < 3.0]
    click_onsets = [b for t, b in zip(onsets, bass, strict=True) if t >= 3.0]
    assert low_freq_onsets and click_onsets
    assert all(level > 0.5 for level in low_freq_onsets)
    assert all(level < 0.2 for level in click_onsets)
