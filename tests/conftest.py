"""Shared fixtures for audio analysis tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture
def click_track(tmp_path: Path) -> Path:
    """A 3-second synthetic click track at 120 BPM — fast enough for librosa in tests."""
    sr = 22050
    duration = 3.0
    y = np.zeros(int(sr * duration), dtype=np.float32)
    for beat in np.arange(0, duration, 0.5):
        start = int(beat * sr)
        y[start : start + 500] = np.sin(np.linspace(0, 200 * np.pi, 500)).astype(np.float32)
    path = tmp_path / "click.wav"
    sf.write(path, y, sr)
    return path
