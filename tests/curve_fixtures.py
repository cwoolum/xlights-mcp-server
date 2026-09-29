"""Shared helpers for value-curve tests."""

from __future__ import annotations

from xlights_mcp.xlights.value_curves import CURVE_SLOTS


def slots(curve: list[tuple[float, float]]) -> list[tuple[int, float]]:
    """A curve's ``(x, level)`` points as ``(slot, level)``."""
    return [(round(x * CURVE_SLOTS), level) for x, level in curve]
