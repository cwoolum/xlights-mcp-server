"""write_plan: validation report, output path rules and the written file."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.sequencer.plan_writer import MAX_REPORTED_ERRORS, write_plan
from xlights_mcp.xlights.xsq_writer import TimingTrack

FIXTURE = Path(__file__).parent / "fixtures" / "show_groups"
ANALYSIS = SongAnalysis(
    file_path="Song.mp3",
    file_name="Song.mp3",
    duration_seconds=8.0,
    beats=BeatMap(tempo=120.0, beat_times=[i * 0.5 for i in range(16)], downbeat_times=[0.0, 2.0, 4.0, 6.0]),
)
PLAN = [
    {"element": "House", "layer": 0, "effect": "Color Wash", "start_ms": 0, "end_ms": 4000},
    {"element": "Lanterns", "layer": 1, "effect": "On", "start_ms": 2000, "end_ms": 2100,
     "palette": {"colors": ["#FF6600"], "brightness": 150}},
]


@pytest.fixture
def show(tmp_path: Path) -> Path:
    folder = tmp_path / "show"
    folder.mkdir()
    shutil.copy(FIXTURE / "xlights_rgbeffects.xml", folder)
    return folder


def _write(show: Path, plan=PLAN, **kw) -> dict:
    return write_plan(plan, ANALYSIS, Path("C:/music/Song.mp3"), show, **kw)


def test_writes_the_sequence_and_reports_it(show):
    report = _write(show, timing_tracks=["Beats", "Bars"])

    assert report["errors"] == [] and report["written"] is True
    assert report["path"] == str(show / "Song.xsq")
    assert (report["elements"], report["effects"], report["max_layer"]) == (2, 2, 1)
    assert report["timing_tracks"] == ["Beats", "Bars"]
    root = ET.parse(show / "Song.xsq").getroot()
    lantern_layers = root.findall("ElementEffects/Element[@name='Lanterns']/EffectLayer")
    assert [len(layer) for layer in lantern_layers] == [0, 1]
    assert any("C_SLIDER_Brightness=150" in (p.text or "") for p in root.findall("ColorPalettes/ColorPalette"))
    beats = root.find("ElementEffects/Element[@name='Beats']/EffectLayer")
    assert [m.get("label") for m in beats][:5] == ["1", "2", "3", "4", "1"]


def test_validate_only_writes_nothing(show):
    report = _write(show, validate_only=True)

    assert report["errors"] == [] and report["written"] is False
    assert not (show / "Song.xsq").exists()


def test_errors_abort_the_write(show):
    report = _write(show, plan=[{**PLAN[0], "element": "Nope"}])

    assert report["written"] is False and report["errors"]
    assert not (show / "Song.xsq").exists()


def test_an_existing_file_needs_overwrite(show):
    (show / "Song.xsq").write_text("old", encoding="utf-8")

    refused = _write(show)
    replaced = _write(show, overwrite=True)

    assert refused["written"] is False and "overwrite" in refused["errors"][0]
    assert replaced["written"] is True
    assert (show / "Song.xsq").read_text(encoding="utf-8") != "old"


def test_name_sets_the_file_name_and_rejects_paths(show):
    assert _write(show, name="My Show")["path"] == str(show / "My Show.xsq")
    assert _write(show, name="Other.xsq", validate_only=True)["path"] == str(show / "Other.xsq")
    for bad in ("../escape", "..", " "):
        assert "name" in _write(show, name=bad)["errors"][0]


def test_duplicate_timing_track_names_are_an_error(show):
    extra = TimingTrack(name="Beats", labels=[[]])

    report = _write(show, timing_tracks=["Beats"], extra_tracks=[extra])

    assert any("Beats" in e and "more than once" in e for e in report["errors"])


def test_never_writes_a_backup(show):
    _write(show)

    assert list(show.glob("*.xbkp")) == []


def test_effect_names_used_in_the_show_are_accepted(show):
    (show / "Other.xsq").write_text(
        '<xsequence><ElementEffects><Element type="model" name="X"><EffectLayer>'
        '<Effect ref="0" name="Future Effect" startTime="0" endTime="25" palette="0"/>'
        "</EffectLayer></Element></ElementEffects></xsequence>",
        encoding="utf-8",
    )

    report = _write(show, plan=[{**PLAN[0], "effect": "Future Effect"}], validate_only=True)

    assert report["errors"] == []


def test_the_error_list_is_capped(show):
    plan = [{**PLAN[0], "element": f"Nope {i}"} for i in range(MAX_REPORTED_ERRORS + 5)]

    report = _write(show, plan=plan)

    assert len(report["errors"]) == MAX_REPORTED_ERRORS + 1
    assert report["errors"][-1] == "... and 5 more errors"
