"""create_sequence's legacy engine groups models by feature-tier groups."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from xlights_mcp.sequencer.engine import (
    _detect_model_groups,
    _generate_guided_preview,
    _sequenceable_models,
)
from xlights_mcp.xlights.show import load_show_config

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


def _analysis():
    return SimpleNamespace(
        sections=[],
        duration_seconds=10.0,
        beats=SimpleNamespace(tempo=120.0, beat_times=[]),
    )


def test_engine_groups_are_the_feature_tier_groups():
    show = load_show_config(SHOW)

    groups, ungrouped, _ = _detect_model_groups(_sequenceable_models(show), show)

    assert set(groups) == {"Roof Edges", "Door", "Pipes", "Lanterns", "Legacy Arches"}
    assert [m.name for m in groups["Roof Edges"]] == ["Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert {m.name for m in ungrouped} == {"Tree 6ft"}


def test_placeholders_are_not_sequenced():
    show = load_show_config(SHOW)

    names = {m.name for m in _sequenceable_models(show)}

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


def test_engine_groups_honor_tier_overrides(tmp_path):
    show_dir = tmp_path / "show"
    shutil.copytree(SHOW, show_dir)
    (show_dir / "xlights-mcp.json").write_text(json.dumps({"tiers": {"Pipes-Odd": "feature"}}), encoding="utf-8")
    show = load_show_config(show_dir)

    groups, _, _ = _detect_model_groups(_sequenceable_models(show), show)

    assert "Pipes-Odd" in groups
