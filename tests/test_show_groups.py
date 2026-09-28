"""Show parsing: placeholders, model height, model groups."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.xlights.models import is_placeholder_name
from xlights_mcp.xlights.show import load_show_models

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Tier 1 Mid - Null 1-2 - Dont Map", True),
        ("Spare - Don't Map", True),
        ("Tier 1 Roof Left - Null - Do Not Map", True),
        ("DONT MAP", True),
        ("Donut Mapper", False),
        ("Roof Left", False),
    ],
)
def test_placeholder_names(name, expected):
    assert is_placeholder_name(name) is expected


def test_models_carry_height_and_placeholder_flag():
    models = {m.name: m for m in load_show_models(SHOW)}

    assert models["Roof Left"].world_pos_y == 150.0
    assert models["Spare - Dont Map"].world_pos_y is None
    assert models["Spare - Dont Map"].is_placeholder is True
    assert models["Roof Left"].is_placeholder is False
