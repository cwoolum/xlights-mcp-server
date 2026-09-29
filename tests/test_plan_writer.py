"""write_plan: validation report, output path rules and the written file."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from show_fixtures import make_analysis, write_xsq_stub

from xlights_mcp.sequencer.plan_writer import MAX_REPORTED_ERRORS, write_plan
from xlights_mcp.xlights.xsq_writer import TimingTrack

ANALYSIS = make_analysis(8.0, [i * 0.5 for i in range(16)], [0.0, 2.0, 4.0, 6.0])
PLAN = [
    {"element": "House", "layer": 0, "effect": "Color Wash", "start_ms": 0, "end_ms": 4000},
    {"element": "Lanterns", "layer": 1, "effect": "On", "start_ms": 2000, "end_ms": 2100,
     "palette": {"colors": ["#FF6600"], "brightness": 150}},
]


def _write(show: Path, plan=PLAN, **kw) -> dict:
    return write_plan(plan, ANALYSIS, Path("C:/music/Song.mp3"), show, **kw)


def test_writes_the_sequence_and_reports_it(show_copy):
    report = _write(show_copy, timing_tracks=["Beats", "Bars"])

    assert report["errors"] == [] and report["written"] is True
    assert report["path"] == str(show_copy / "Song.xsq")
    assert (report["elements"], report["effects"], report["max_layer"]) == (2, 2, 1)
    assert report["timing_tracks"] == ["Beats", "Bars"]
    root = ET.parse(show_copy / "Song.xsq").getroot()
    lantern_layers = root.findall("ElementEffects/Element[@name='Lanterns']/EffectLayer")
    assert [len(layer) for layer in lantern_layers] == [0, 1]
    assert any("C_SLIDER_Brightness=150" in (p.text or "") for p in root.findall("ColorPalettes/ColorPalette"))
    beats = root.find("ElementEffects/Element[@name='Beats']/EffectLayer")
    assert [m.get("label") for m in beats][:5] == ["1", "2", "3", "4", "1"]


def test_validate_only_writes_nothing(show_copy):
    report = _write(show_copy, validate_only=True)

    assert report["errors"] == [] and report["written"] is False
    assert not (show_copy / "Song.xsq").exists()


def test_errors_abort_the_write(show_copy):
    report = _write(show_copy, plan=[{**PLAN[0], "element": "Nope"}])

    assert report["written"] is False and report["errors"]
    assert not (show_copy / "Song.xsq").exists()


def test_an_existing_file_needs_overwrite(show_copy):
    (show_copy / "Song.xsq").write_text("old", encoding="utf-8")

    refused = _write(show_copy)
    replaced = _write(show_copy, overwrite=True)

    assert refused["written"] is False and "overwrite" in refused["errors"][0]
    assert replaced["written"] is True
    assert (show_copy / "Song.xsq").read_text(encoding="utf-8") != "old"


def test_name_sets_the_file_name_and_rejects_paths(show_copy):
    assert _write(show_copy, name="My Show")["path"] == str(show_copy / "My Show.xsq")
    assert _write(show_copy, name="Other.xsq", validate_only=True)["path"] == str(show_copy / "Other.xsq")
    assert _write(show_copy, name="Foo.XSQ", validate_only=True)["path"] == str(show_copy / "Foo.xsq")
    for bad in ("../escape", "..", " ", "a\\b", "a/b"):
        assert "without folders" in _write(show_copy, name=bad)["errors"][0]


def test_names_windows_forbids_are_an_error_naming_the_character(show_copy):
    for bad, char in (("a?b", "?"), ('a"b', '"'), ("Who Let the Dogs Out?", "?"), ("a*b", "*")):
        error = _write(show_copy, name=bad)["errors"][0]
        assert "Windows doesn't allow" in error and repr(char) in error
    assert "Windows doesn't allow" in _write(show_copy, name="a\x01b")["errors"][0]


def test_an_invalid_name_leaves_the_report_path_empty(show_copy):
    assert _write(show_copy, name="a?b")["path"] is None
    assert _write(show_copy, name="../x")["path"] is None


def test_a_timing_track_cannot_share_a_name_with_a_model_or_group(show_copy):
    extra = TimingTrack(name="Lanterns", labels=[[]])

    report = _write(show_copy, extra_tracks=[extra])

    assert any("'Lanterns'" in e and "same name as a model or group" in e for e in report["errors"])
    assert not (show_copy / "Song.xsq").exists()


def test_duplicate_timing_track_names_are_an_error(show_copy):
    extra = TimingTrack(name="Beats", labels=[[]])

    report = _write(show_copy, timing_tracks=["Beats"], extra_tracks=[extra])

    assert any("Beats" in e and "more than once" in e for e in report["errors"])


def test_never_writes_a_backup(show_copy):
    (show_copy / "Song.xsq").write_text("old", encoding="utf-8")

    _write(show_copy, overwrite=True)

    assert list(show_copy.glob("*.xbkp")) == []


def test_effect_names_used_in_the_show_are_accepted(show_copy):
    write_xsq_stub(
        show_copy / "Other.xsq",
        '<Element type="model" name="X"><EffectLayer>'
        '<Effect ref="0" name="Future Effect" startTime="0" endTime="25" palette="0"/>'
        "</EffectLayer></Element>",
    )

    report = _write(show_copy, plan=[{**PLAN[0], "effect": "Future Effect"}], validate_only=True)

    assert report["errors"] == []


def test_the_error_list_is_capped(show_copy):
    plan = [{**PLAN[0], "element": f"Nope {i}"} for i in range(MAX_REPORTED_ERRORS + 5)]

    report = _write(show_copy, plan=plan)

    assert len(report["errors"]) == MAX_REPORTED_ERRORS + 1
    assert report["errors"][-1] == "... and 5 more errors"


def test_the_written_head_carries_the_given_xlights_version(show_copy):
    _write(show_copy, xlights_version="2026.17")

    assert ET.parse(show_copy / "Song.xsq").getroot().findtext("head/version") == "2026.17"


def test_a_brightness_curve_is_written_into_the_palette(show_copy):
    plan = [{
        "element": "House", "layer": 0, "effect": "Color Wash", "start_ms": 0, "end_ms": 4000,
        "palette": {"colors": ["#FFFFFF"], "brightness": [[0, 100], [4000, 300]]},
    }]

    report = _write(show_copy, plan=plan)

    assert report["errors"] == [] and report["written"] is True
    palettes = [p.text or "" for p in ET.parse(show_copy / "Song.xsq").getroot().findall("ColorPalettes/ColorPalette")]
    assert any(
        "C_VALUECURVE_Brightness=" in text and "Type=Custom" in text and "Values=0.000:0.2500;1.000:0.7500|" in text
        and "C_SLIDER_Brightness" not in text
        for text in palettes
    )
