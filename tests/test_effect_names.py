"""Effect names the writer accepts, and the library list_effects advertises."""

from __future__ import annotations

from show_fixtures import write_xsq_stub

from xlights_mcp.xlights.effects import (
    MODEL_EFFECT_MAP,
    MUSICAL_EFFECT_MAP,
    XLIGHTS_EFFECT_NAMES,
    get_effect_library,
    known_effect_names,
)
from xlights_mcp.xlights.xsq_writer import GENERATOR_COMMENT


def test_every_advertised_effect_passes_the_writer_check():
    assert {e["name"] for e in get_effect_library()} <= XLIGHTS_EFFECT_NAMES


def test_effect_maps_only_name_real_effects():
    for mapping in (MUSICAL_EFFECT_MAP, MODEL_EFFECT_MAP):
        for names in mapping.values():
            assert set(names) <= XLIGHTS_EFFECT_NAMES


def test_chase_is_advertised_as_singlestrand():
    names = [e["name"] for e in get_effect_library()]

    assert "Chase" not in names
    assert names.count("SingleStrand") == 1


def test_show_sequences_add_their_effect_names(tmp_path):
    write_xsq_stub(
        tmp_path / "a.xsq",
        '<Element type="model" name="X"><EffectLayer>'
        '<Effect ref="0" name="Custom Thing" startTime="0" endTime="25" palette="0"/>'
        "</EffectLayer></Element>",
    )

    assert "Custom Thing" in known_effect_names(tmp_path)
    assert "Custom Thing" not in known_effect_names(None)


def test_sequences_written_by_this_server_are_skipped(tmp_path):
    (tmp_path / "ours.xsq").write_text(
        f"<xsequence><head><comment>{GENERATOR_COMMENT}</comment></head><ElementEffects>"
        '<Element type="model" name="X"><EffectLayer>'
        '<Effect ref="0" name="Typo Effect" startTime="0" endTime="25" palette="0"/>'
        "</EffectLayer></Element></ElementEffects></xsequence>",
        encoding="utf-8",
    )

    assert known_effect_names(tmp_path) == XLIGHTS_EFFECT_NAMES


def test_timing_marks_are_not_effect_names(tmp_path):
    write_xsq_stub(
        tmp_path / "a.xsq",
        '<Element type="timing" name="Beats"><EffectLayer>'
        '<Effect label="1" startTime="0" endTime="500"/>'
        "</EffectLayer></Element>",
    )

    assert known_effect_names(tmp_path) == XLIGHTS_EFFECT_NAMES
