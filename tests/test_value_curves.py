"""Custom value curves: snapping points to slots and the curve string."""

from __future__ import annotations

import pytest
from curve_fixtures import slots

from xlights_mcp.xlights.value_curves import custom_curve_points, custom_curve_string

MERGED_50 = "brightness points closer than one curve slot (50 ms) were merged"
MERGED_100 = "brightness points closer than one curve slot (100 ms) were merged"


@pytest.mark.parametrize(
    "points, start, end, expected, warnings",
    [
        pytest.param([(0, 100), (10000, 300)], 0, 10000, [(0, 100), (200, 300)], [], id="ramp"),
        pytest.param(
            [(0, 100), (5000, 100), (5000, 250), (10000, 250)], 0, 10000,
            [(0, 100), (100, 100), (101, 250), (200, 250)], [], id="step goes one slot later",
        ),
        pytest.param(
            [(2000, 100), (8000, 200)], 0, 10000,
            [(0, 100), (40, 100), (160, 200), (200, 200)], [], id="missing ends hold the first and last values",
        ),
        pytest.param(
            [(0, 100), (5000, 100), (5000, 250), (5025, 300), (10000, 300)], 0, 10000,
            [(0, 100), (100, 100), (101, 300), (200, 300)], [MERGED_50], id="a point after a step merges into it",
        ),
        pytest.param(
            [(0, 100), (10000, 100), (10000, 300)], 0, 10000,
            [(0, 100), (199, 100), (200, 300)], [], id="a step at the end uses the last two slots",
        ),
        pytest.param(
            [(0, 100), (9950, 50), (10000, 100), (10000, 300)], 0, 10000,
            [(0, 100), (199, 100), (200, 300)], [MERGED_50], id="an end step displacing slot 199 warns",
        ),
        pytest.param(
            [(0, 100), (25, 200), (75, 300), (10000, 300)], 0, 10000,
            [(0, 100), (1, 200), (2, 300), (200, 300)], [], id="slots round half up",
        ),
        pytest.param(
            [(0, 100), (1234, 200), (4000, 300)], 0, 4000,
            [(0, 100), (62, 200), (200, 300)], [], id="a short effect snaps without warning",
        ),
        pytest.param(
            [(0, 100), (1000, 120), (1030, 140), (20000, 140)], 0, 20000,
            [(0, 100), (10, 140), (200, 140)],
            ["brightness curve points snap to 100 ms steps on this 20.0 s effect", MERGED_100],
            id="close points on a long effect snap and merge, keeping the later value",
        ),
    ],
)
def test_points_snap_to_slots(points, start, end, expected, warnings):
    curve, got = custom_curve_points(points, start, end)

    assert slots(curve) == expected
    assert got == warnings


@pytest.mark.parametrize(
    "points, expected",
    [
        pytest.param([(1000, 100), (2000, 300)], [(0, 100), (200, 200)], id="ramp cut at the clip"),
        pytest.param(
            [(1000, 100), (1400, 100), (1600, 200), (2000, 300)],
            [(0, 100), (160, 100), (200, 150)], id="points after the clip are dropped",
        ),
        pytest.param([(1600, 250), (2000, 300)], [(0, 250), (200, 250)], id="all points after the clip hold the first"),
        pytest.param(
            [(1000, 100), (1500, 100), (1500, 300), (2000, 300)],
            [(0, 100), (199, 100), (200, 300)], id="a step at the clip is kept",
        ),
    ],
)
def test_points_are_clipped_to_the_clip_end(points, expected):
    curve, warnings = custom_curve_points(points, 1000, 2000, clip_end_ms=1500)

    assert slots(curve) == expected
    assert warnings == []


def test_a_clip_end_after_the_end_changes_nothing():
    points = [(0, 100), (10000, 300)]

    assert custom_curve_points(points, 0, 10000, clip_end_ms=20000) == custom_curve_points(points, 0, 10000)


def test_the_warning_label_names_the_curve():
    _, warnings = custom_curve_points([(0, 100), (1000, 200), (1030, 300), (20000, 300)], 0, 20000, label="speed")

    assert warnings == [
        "speed curve points snap to 100 ms steps on this 20.0 s effect",
        "speed points closer than one curve slot (100 ms) were merged",
    ]


def test_a_curve_string_normalises_levels_over_min_and_max():
    text = custom_curve_string("Brightness", 0, 400, [(0.0, 100), (0.005, 200), (1.0, 300)])

    assert text == (
        "Active=TRUE|Id=ID_VALUECURVE_Brightness|Type=Custom|Min=0.00|Max=400.00|RV=TRUE"
        "|Values=0.000:0.2500;0.005:0.5000;1.000:0.7500|"
    )
    assert "Id=ID_VALUECURVE_Speed|Type=Custom|Min=100.00|Max=500.00|RV=TRUE|Values=0.000:0.5000;1.000:1.0000|" in (
        custom_curve_string("Speed", 100, 500, [(0.0, 300), (1.0, 500)])
    )
