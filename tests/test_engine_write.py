"""create_sequence's auto mode still writes a well-formed sequence through write_xsq."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from show_fixtures import make_analysis

from xlights_mcp.audio.cache import save_cached
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.config import AudioConfig
from xlights_mcp.sequencer.engine import generate_sequence


def test_auto_mode_writes_effects_with_refs_and_palettes(
    tmp_path: Path, click_track: Path, show_copy: Path
):
    audio = AudioConfig(cache_dir=tmp_path / "cache")
    analysis = make_analysis(
        20.0,
        np.arange(0, 20, 0.5).tolist(),
        np.arange(0, 20, 2.0).tolist(),
        path=click_track,
        sections=[SongSection(label="chorus", start_time=0.0, end_time=20.0, energy_level=0.8)],
    )
    save_cached(analysis, click_track, audio.cache_dir)

    result = generate_sequence(mp3_path=click_track, show_path=show_copy, mode="auto", audio_config=audio)

    root = ET.parse(result["output_path"]).getroot()
    effects = [e for e in root.iter("Effect") if e.get("name")]
    assert effects
    assert all(e.get("ref") is not None and e.get("palette") is not None for e in effects)
    assert result["success"] is True
