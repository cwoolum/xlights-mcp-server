"""create_sequence's auto mode still writes a well-formed sequence through write_xsq."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.cache import save_cached
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.config import AudioConfig
from xlights_mcp.sequencer.engine import generate_sequence

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


def test_auto_mode_writes_effects_with_refs_and_palettes(tmp_path: Path, click_track: Path):
    show = tmp_path / "show"
    show.mkdir()
    shutil.copy(SHOW / "xlights_rgbeffects.xml", show)
    audio = AudioConfig(cache_dir=tmp_path / "cache")
    save_cached(
        SongAnalysis(
            file_path=str(click_track),
            file_name=click_track.name,
            duration_seconds=20.0,
            beats=BeatMap(
                tempo=120.0,
                beat_times=np.arange(0, 20, 0.5).tolist(),
                downbeat_times=np.arange(0, 20, 2.0).tolist(),
            ),
            sections=[SongSection(label="chorus", start_time=0.0, end_time=20.0, energy_level=0.8)],
        ),
        click_track,
        audio.cache_dir,
    )

    result = generate_sequence(mp3_path=click_track, show_path=show, mode="auto", audio_config=audio)

    root = ET.parse(result["output_path"]).getroot()
    effects = [e for e in root.iter("Effect") if e.get("name")]
    assert effects
    assert all(e.get("ref") is not None and e.get("palette") is not None for e in effects)
