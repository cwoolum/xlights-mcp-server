"""profile_sequence on a small hand-made-style sequence with hand-derived numbers.

Derivation for `fixtures/sequences/Human Style.xsq` (10 s, Off doesn't count as lit).

Lit spans, in ms:
- House: [0,4000) and [6500,10000)
- Roof Edges: [2000,6000)
- Lanterns: [1000,1500) and [3000,5000)
- Lantern1: [8000,9000); its Off effect on layer 0 is dark
- Door: [0,2500), merged from the overlapping [0,2000) and [1500,2500)

Elements lit at once, sampled at t = 0, 50, ..., 9950 (200 samples):

    time (ms)     lit   samples
    0-1000         2      20
    1000-1500      3      10
    1500-2000      2      10
    2000-2500      3      10
    2500-3000      2      10
    3000-4000      3      20
    4000-5000      2      20
    5000-6000      1      20
    6000-6500      0      10
    6500-8000      1      30
    8000-9000      2      20
    9000-10000     1      20

Totals: 10 samples with 0 lit, 70 with 1, 80 with 2, 40 with 3.
- median = 2 (sorted samples 99 and 100 are both 2)
- p90 = 3 (linear percentile position 179.1, and samples 179 and 180 are both 3)
- max = 3
- dark share = 10/200 = 0.05

Parent share (a group's lit time that overlaps its contained elements' lit time):
- House holds Roof Edges and Door. Their union is [0,6000). House is lit for 4000 + 3500 = 7500 ms,
  and 4000 ms of that is inside the union: 4000/7500 = 0.53.
- Lanterns holds Lantern1 [8000,9000), which never overlaps Lanterns' lit time: 0.0.
- Roof Edges and Door hold nothing lit, so they're omitted.

Elements with effects: groups Door, House, Lanterns, Roof Edges (4) and the model Lantern1 (1);
Tree 6ft has no effects. 9 effects in total, and one overlap within a layer (Door, layer 0).

Rows, sorted by effect count descending then name: median length is over effect lengths, lit share is
lit time / 10000 ms.

    element      effects  layers  median_ms  lit_share  top effects
    Door            2     [0]       1500       0.25     On
    House           2     [0]       3750       0.75     On, Color Wash
    Lantern1        2     [0, 1]    4500       0.10     Off, On
    Lanterns        2     [0]       1250       0.25     On, Twinkle
    Roof Edges      1     [0]       4000       0.40     SingleStrand
"""

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
        "median_ms": 3750, "lit_share": 0.75, "top_effects": ["On", "Color Wash"], "sub_effects": 0,
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


def _xsq(tmp_path: Path, body: str, duration_s: str = "10.000") -> Path:
    path = tmp_path / "inline.xsq"
    path.write_text(
        f"<xsequence><head><sequenceDuration>{duration_s}</sequenceDuration></head>"
        f"<ElementEffects>{body}</ElementEffects></xsequence>",
        encoding="utf-8",
    )
    return path


def test_strand_node_and_submodel_effects_count_toward_the_element(tmp_path):
    path = _xsq(
        tmp_path,
        """
        <Element type="model" name="Door">
          <EffectLayer><Effect name="On" startTime="0" endTime="1000"/></EffectLayer>
          <Strand index="0"><Effect name="Twinkle" startTime="2000" endTime="3000"/></Strand>
          <Strand index="1"><Node index="0"><Effect name="Shimmer" startTime="4000" endTime="4500"/></Node></Strand>
          <SubModelEffectLayer name="Left"><Effect name="Pinwheel" startTime="6000" endTime="7000"/></SubModelEffectLayer>
        </Element>
        <Element type="model" name="Lantern1">
          <EffectLayer/>
          <Strand index="0"><Effect name="On" startTime="0" endTime="2000"/></Strand>
        </Element>
        """,
    )

    profile = profile_sequence(path, SHOW)

    rows = {r["element"]: r for r in profile["elements"]}
    assert rows["Door"] == {
        "element": "Door", "kind": "group", "layers": [0], "effects": 4, "sub_effects": 3,
        "median_ms": 1000, "lit_share": 0.35, "top_effects": ["On", "Twinkle", "Shimmer"],
    }
    assert rows["Lantern1"]["layers"] == []
    assert (rows["Lantern1"]["effects"], rows["Lantern1"]["sub_effects"], rows["Lantern1"]["lit_share"]) == (1, 1, 0.2)
    assert profile["total_effects"] == 5
    assert profile["overlaps_within_layer"] == 0
    assert profile["lit_at_once"]["max"] == 2


def test_lit_spans_are_clipped_to_the_sequence(tmp_path):
    path = _xsq(
        tmp_path,
        """
        <Element type="model" name="Door"><EffectLayer>
          <Effect name="On" startTime="0" endTime="3000"/>
        </EffectLayer></Element>
        <Element type="model" name="Lantern1"><EffectLayer>
          <Effect name="On" startTime="-500" endTime="500"/>
        </EffectLayer></Element>
        """,
        duration_s="1.000",
    )

    profile = profile_sequence(path, SHOW)

    rows = {r["element"]: r for r in profile["elements"]}
    assert rows["Door"]["lit_share"] == 1.0
    assert rows["Lantern1"]["lit_share"] == 0.5
    assert profile["lit_at_once"] == {"median": 1.5, "p90": 2, "max": 2}
    assert profile["dark_share"] == 0.0


def test_an_effect_lying_wholly_outside_the_sequence_is_not_lit(tmp_path):
    path = _xsq(
        tmp_path,
        '<Element type="model" name="Door"><EffectLayer><Effect name="On" startTime="2000" endTime="3000"/>'
        "</EffectLayer></Element>",
        duration_s="1.000",
    )

    profile = profile_sequence(path, SHOW)

    assert profile["elements"][0]["lit_share"] == 0.0
    assert profile["dark_share"] == 1.0


def test_duplicate_element_names_are_merged_into_one_row(tmp_path):
    path = _xsq(
        tmp_path,
        """
        <Element type="model" name="Door"><EffectLayer>
          <Effect name="On" startTime="0" endTime="1000"/>
        </EffectLayer></Element>
        <Element type="model" name="Door"><EffectLayer>
          <Effect name="Twinkle" startTime="2000" endTime="3000"/>
        </EffectLayer></Element>
        """,
    )

    profile = profile_sequence(path, SHOW)

    assert [r["element"] for r in profile["elements"]] == ["Door"]
    assert profile["elements"][0]["effects"] == 2
    assert profile["elements"][0]["lit_share"] == 0.2
    assert profile["elements_with_effects"] == {"groups": 1, "models": 0, "unknown": 0}
    assert profile["total_effects"] == 2
    assert profile["lit_at_once"]["max"] == 1


def test_an_empty_sequence_is_all_dark(tmp_path):
    path = tmp_path / "empty.xsq"
    path.write_text("<xsequence><ElementEffects/></xsequence>", encoding="utf-8")

    profile = profile_sequence(path, SHOW)

    assert profile["duration_ms"] == 0
    assert profile["lit_at_once"] == {"median": 0, "p90": 0, "max": 0}
    assert profile["dark_share"] == 1.0
    assert profile["elements"] == []
    assert profile["total_effects"] == 0
