"""One end-to-end check against the real demucs/madmom backends.

Everything else in the suite stubs these out (see the autouse fixture in
conftest.py) for speed and reproducibility on machines without the optional
[separation]/[beats] extras installed. This test is the one place that
exercises the real thing, so a change to either integration still gets
caught. It is excluded from the default run (see `addopts` in pyproject.toml)
because it is slow and requires both backends installed; run it explicitly
with:

    .venv/Scripts/python -m pytest -m real_backends
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.audio.analyzer import full_analysis
from xlights_mcp.config import AudioConfig


@pytest.mark.real_backends
def test_full_analysis_with_real_backends(click_track: Path, tmp_path: Path):
    pytest.importorskip("demucs")
    pytest.importorskip("madmom")

    analysis = full_analysis(click_track, AudioConfig(cache_dir=tmp_path / "cache"))

    assert analysis.duration_seconds == pytest.approx(3.0, abs=0.1)
    assert analysis.beats.tempo > 0
    assert analysis.stem_analysis.available
    assert analysis.beats.beat_source == "madmom"
