"""profile_sequence on a small hand-made-style sequence with hand-derived numbers."""

from __future__ import annotations

from pathlib import Path

from show_fixtures import SHOW_GROUPS

from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.profile import MAX_ELEMENT_ROWS, profile_sequence
from xlights_mcp.xlights.show import load_show_config
from xlights_mcp.xlights.xsq_writer import EffectPlacement, SequenceSpec, write_xsq

HUMAN_STYLE = Path(__file__).parent / "fixtures" / "sequences" / "Human Style.xsq"
SHOW = load_show_config(SHOW_GROUPS)


def test_summary_counts():
    profile = profile_sequence(HUMAN_STYLE, SHOW)

    assert profile["duration_ms"] == 10000
    assert profile["elements_with_effects"] == {"groups": 4, "models": 1, "unknown": 0}
    assert profile["total_effects"] == 9
    assert profile["timing_tracks"] == ["Beats"]
    assert profile["overlaps_within_layer"] == 1


def test_concurrency_and_dark_share():
    profile = profile_sequence(HUMAN_STYLE, SHOW)

    assert profile["lit_at_once"] == {"median": 2, "p90": 3, "max": 3}
    assert profile["dark_share"] == 0.05


def test_parent_lit_with_contained_elements():
    assert profile_sequence(HUMAN_STYLE, SHOW)["parent_lit_with_contained"] == {"House": 0.53, "Lanterns": 0.0}


def test_element_rows():
    rows = {r["element"]: r for r in profile_sequence(HUMAN_STYLE, SHOW)["elements"]}

    assert list(rows) == ["Door", "House", "Lantern1", "Lanterns", "Roof Edges"]
    assert rows["House"] == {
        "element": "House", "kind": "group", "layers": [0], "effects": 2,
        "median_ms": 3750, "lit_share": 0.75, "top_effects": ["On", "Color Wash"],
    }
    assert rows["Lantern1"]["kind"] == "model"
    assert rows["Lantern1"]["layers"] == [0, 1]
    assert rows["Lantern1"]["lit_share"] == 0.1
    assert rows["Door"]["lit_share"] == 0.25


def test_rows_are_capped_and_the_rest_summarised(tmp_path):
    effects = [
        EffectPlacement(model_name=f"M{i:02d}", effect_name="On", start_time_ms=0, end_time_ms=1000)
        for i in range(MAX_ELEMENT_ROWS + 5)
    ]
    path = tmp_path / "many.xsq"
    write_xsq(SequenceSpec(duration_ms=2000, effects=effects), ShowConfig(show_path=".", show_name="t"), path)

    profile = profile_sequence(path, SHOW)

    assert len(profile["elements"]) == MAX_ELEMENT_ROWS
    assert profile["other_elements"] == {"count": 5, "effects": 5}
    assert profile["elements_with_effects"]["unknown"] == MAX_ELEMENT_ROWS + 5


def test_no_summary_when_under_the_cap():
    assert profile_sequence(HUMAN_STYLE, SHOW)["other_elements"] is None


def test_duration_falls_back_to_the_last_effect_end(tmp_path):
    path = tmp_path / "nohead.xsq"
    path.write_text(
        '<xsequence><ElementEffects><Element type="model" name="Door"><EffectLayer>'
        '<Effect name="On" startTime="0" endTime="2000"/></EffectLayer></Element></ElementEffects></xsequence>',
        encoding="utf-8",
    )

    assert profile_sequence(path, SHOW)["duration_ms"] == 2000
