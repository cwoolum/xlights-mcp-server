"""The baseline and guided preview honour the show's groups, tiers and placeholders."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from show_fixtures import make_analysis

from xlights_mcp.audio.sections import SongSection
from xlights_mcp.sequencer.engine import _generate_guided_preview, build_baseline_plan
from xlights_mcp.xlights.show import load_show_config

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


def _analysis():
    return SimpleNamespace(
        sections=[],
        duration_seconds=10.0,
        beats=SimpleNamespace(tempo=120.0, beat_times=[]),
    )


def test_placeholders_are_not_sequenced():
    show = load_show_config(SHOW)

    names = {m.name for m in show.real_models}

    assert "Spare - Dont Map" not in names
    assert "Roof Mid - Null - Do Not Map" not in names
    assert "Tree 6ft" in names


def test_guided_preview_omits_placeholders():
    show = load_show_config(SHOW)

    preview = _generate_guided_preview(_analysis(), show)

    listed = {name for names in preview["models_by_category"].values() for name in names}
    assert "Tree 6ft" in listed
    assert "Spare - Dont Map" not in listed
    assert "Roof Mid - Null - Do Not Map" not in listed


def test_baseline_honors_tier_overrides(tmp_path):
    show_dir = tmp_path / "show"
    shutil.copytree(SHOW, show_dir)
    (show_dir / "xlights-mcp.json").write_text(json.dumps({"tiers": {"Pipes-Odd": "feature"}}), encoding="utf-8")
    show = load_show_config(show_dir)
    analysis = make_analysis(
        8.0, [], [0.0, 2.0, 4.0, 6.0],
        sections=[
            SongSection(label="verse", start_time=0.0, end_time=4.0),
            SongSection(label="verse", start_time=4.0, end_time=8.0),
        ],
    )

    elements = {p["element"] for p in build_baseline_plan(analysis, show, ["#FFFFFF"])}

    assert "Pipes-Odd" in elements
