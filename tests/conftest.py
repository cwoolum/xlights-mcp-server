"""Shared fixtures for audio analysis tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture(autouse=True)
def _stub_heavy_backends(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic: demucs/madmom may be genuinely installed in a dev
    venv (see pyproject's separation/beats extras), and without this stub tests
    that exercise full_analysis would invoke them for real -- slow, and not
    reproducible on a machine without those extras installed.

    Stubs separate_stems (as if demucs were never installed) and _madmom_grid (as
    if madmom were never installed). A test that wants the real backends should
    monkeypatch these itself -- that patch is applied after this fixture's, on the
    same shared `monkeypatch` instance, so it wins -- or be marked
    @pytest.mark.real_backends to skip this stub entirely.
    """
    if request.node.get_closest_marker("real_backends"):
        return

    from xlights_mcp.audio import analyzer, beats
    from xlights_mcp.audio.separator import StemPaths

    monkeypatch.setattr(analyzer, "separate_stems", lambda _path: StemPaths(available=False))
    monkeypatch.setattr(beats, "_madmom_grid", lambda _path: None)


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
