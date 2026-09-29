"""write_xsq output structure."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from xlights_mcp.xlights.models import LightModel, ModelGroup, ShowConfig
from xlights_mcp.xlights.palettes import DEFAULT_PALETTE, ColorPalette
from xlights_mcp.xlights.xsq_writer import (
    DEFAULT_XLIGHTS_VERSION,
    EffectPlacement,
    SequenceSpec,
    TimingTrack,
    TimingTrackLabel,
    write_xsq,
)

SHOW = ShowConfig(show_path=".", show_name="test")


def _write(tmp_path: Path, *effects: EffectPlacement, **spec_kw) -> ET.Element:
    out = tmp_path / "s.xsq"
    write_xsq(SequenceSpec(duration_ms=10000, effects=list(effects), **spec_kw), SHOW, out)
    return ET.parse(out).getroot()


def _on(element: str, **kw) -> EffectPlacement:
    return EffectPlacement(model_name=element, effect_name="On", start_time_ms=0, end_time_ms=500, **kw)


def _placed(root: ET.Element) -> list[ET.Element]:
    return root.findall("ElementEffects/Element/EffectLayer/Effect")


def test_a_layer_two_placement_keeps_its_layer_position(tmp_path):
    root = _write(tmp_path, _on("Roof", layer=2))

    layers = root.findall("ElementEffects/Element[@name='Roof']/EffectLayer")
    assert [len(layer) for layer in layers] == [0, 0, 1]


def test_palettes_are_collected_from_placements_and_deduplicated(tmp_path):
    red = ColorPalette(colors=["#FF0000"], active_colors=[1])
    blue = ColorPalette(colors=["#0000FF"], active_colors=[1], brightness=50)

    root = _write(tmp_path, _on("A", palette=red), _on("B", palette=red), _on("C", palette=blue))

    assert [p.text for p in root.findall("ColorPalettes/ColorPalette")] == [
        red.to_xlights_string(),
        blue.to_xlights_string(),
    ]
    assert {e.get("palette") for e in _placed(root)} == {"0", "1"}


def test_an_effect_without_a_palette_gets_the_default_palette(tmp_path):
    root = _write(tmp_path, _on("A"))

    assert root.find("ColorPalettes/ColorPalette").text == DEFAULT_PALETTE.to_xlights_string()
    assert _placed(root)[0].get("palette") == "0"


def test_settings_keep_their_order_and_every_effect_refs_them(tmp_path):
    root = _write(
        tmp_path,
        _on("A", settings={"Z_LAST": "1", "A_FIRST": "2"}),
        _on("B"),
    )

    db = [e.text or "" for e in root.findall("EffectDB/Effect")]
    by_element = {
        el.get("name"): el.find("EffectLayer/Effect").get("ref")
        for el in root.findall("ElementEffects/Element")
    }
    assert db[int(by_element["A"])] == "Z_LAST=1,A_FIRST=2"
    assert db[int(by_element["B"])] == ""


def test_timing_tracks_come_before_models_in_both_element_lists(tmp_path):
    track = TimingTrack(name="Beats", labels=[[TimingTrackLabel(label="1", start_time_ms=0, end_time_ms=500)]])

    root = _write(tmp_path, _on("Roof"), timing_tracks=[track])

    display = root.findall("DisplayElements/Element")
    assert [(e.get("type"), e.get("name")) for e in display] == [("timing", "Beats"), ("model", "Roof")]
    assert display[0].get("views") == ""
    effects = root.findall("ElementEffects/Element")
    assert [(e.get("type"), e.get("name")) for e in effects] == [("timing", "Beats"), ("model", "Roof")]


def test_only_elements_with_placements_are_listed(tmp_path):
    show = ShowConfig(show_path=".", show_name="test", models=[LightModel(name=f"M{n}") for n in range(30)])
    out = tmp_path / "s.xsq"

    write_xsq(SequenceSpec(duration_ms=10000, effects=[_on("M7")]), show, out)

    root = ET.parse(out).getroot()
    assert [e.get("name") for e in root.findall("DisplayElements/Element")] == ["M7"]
    assert [e.get("name") for e in root.findall("ElementEffects/Element")] == ["M7"]


def test_model_elements_follow_the_show_groups_first_then_models_then_strangers(tmp_path):
    show = ShowConfig(
        show_path=".",
        show_name="test",
        models=[LightModel(name="Zebra"), LightModel(name="Apple")],
        model_groups=[ModelGroup(name="Yard"), ModelGroup(name="All")],
    )
    out = tmp_path / "s.xsq"
    placements = [_on(name) for name in ("Apple", "Stray B", "Zebra", "All", "Stray A", "Yard")]

    write_xsq(SequenceSpec(duration_ms=10000, effects=placements), show, out)

    root = ET.parse(out).getroot()
    expected = ["Yard", "All", "Zebra", "Apple", "Stray A", "Stray B"]
    assert [e.get("name") for e in root.findall("DisplayElements/Element")] == expected
    assert [e.get("name") for e in root.findall("ElementEffects/Element")] == expected


def test_the_head_carries_the_spec_version(tmp_path):
    root = _write(tmp_path, _on("Roof"), xlights_version="2026.17")

    assert root.findtext("head/version") == "2026.17"


def test_the_head_version_defaults_to_the_generator_default(tmp_path):
    assert _write(tmp_path, _on("Roof")).findtext("head/version") == DEFAULT_XLIGHTS_VERSION
