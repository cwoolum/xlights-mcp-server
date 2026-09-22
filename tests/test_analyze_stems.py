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
    print(f"detected silence span: ({start!r}, {end!r})")
    assert 2.0 <= start <= 2.5
    assert 4.3 <= end <= 4.6
