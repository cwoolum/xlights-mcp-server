"""create_sequence's palette_hint: colour names and hex, separated by commas and/or "and"."""

from __future__ import annotations

import pytest

from xlights_mcp.xlights.palettes import COLOR_NAMES, palette_colors, parse_palette_hint


@pytest.mark.parametrize(
    "hint, colors",
    [
        ("red and green", ["#FF0000", "#00FF00"]),
        ("orange, purple and warm white", [COLOR_NAMES["orange"], COLOR_NAMES["purple"], COLOR_NAMES["warm white"]]),
        ("Red,  GREEN", ["#FF0000", "#00FF00"]),
        ("#7fe7ff and ice", ["#7FE7FF", COLOR_NAMES["ice"]]),
        ("red and red", ["#FF0000"]),
    ],
)
def test_recognised_colours(hint, colors):
    assert parse_palette_hint(hint) == (colors, [])


def test_unrecognised_words_are_reported():
    assert parse_palette_hint("red and teal") == (["#FF0000"], ["teal"])


def test_at_most_eight_colours():
    hint = "red, green, blue, white, yellow, orange, gold, purple, pink"

    assert len(parse_palette_hint(hint)[0]) == 8


def test_the_word_and_inside_a_name_is_not_a_separator():
    assert parse_palette_hint("sandy") == ([], ["sandy"])


def test_no_recognised_colour_falls_back_to_the_theme_palette():
    colors, unknown = palette_colors("teal", "halloween")

    assert colors == ["#FF6600", "#800080", "#00FF00"]
    assert unknown == ["teal"]


def test_no_hint_uses_the_theme_palette():
    assert palette_colors(None, "christmas") == (["#FF0000", "#00FF00", "#FFFFFF"], [])
