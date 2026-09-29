"""xLights Custom value curves: points across an effect, snapped to the curve's slots."""

from __future__ import annotations

import math

CURVE_SLOTS = 200
_SNAP_WARNING_MS = 25


def custom_curve_points(
    points_ms: list[tuple[float, float]],
    start_ms: float,
    end_ms: float,
    clip_end_ms: float | None = None,
    label: str = "brightness",
) -> tuple[list[tuple[float, float]], list[str]]:
    """Snap ``(t_ms, level)`` points to the ``CURVE_SLOTS`` slots across an effect, as ``(x, level)`` pairs with warnings.

    ``end_ms`` is where the points' effect would end; with ``clip_end_ms`` earlier than that, points after it are
    dropped, a point holding the interpolated level is added there, and the slots span ``start_ms``-``clip_end_ms``.
    """
    if clip_end_ms is not None and clip_end_ms < end_ms:
        points_ms, end_ms = _clipped_to(points_ms, clip_end_ms), clip_end_ms
    length = end_ms - start_ms
    slot_ms = length / CURVE_SLOTS
    natural = [math.floor((t - start_ms) / length * CURVE_SLOTS + 0.5) for t, _ in points_ms]
    slots = _ordered_slots(natural, [t for t, _ in points_ms])
    by_slot = {slot: level for slot, (_, level) in zip(slots, points_ms)}
    by_slot.setdefault(0, by_slot[min(by_slot)])
    by_slot.setdefault(CURVE_SLOTS, by_slot[max(by_slot)])
    warnings = []
    if any(abs(slot * slot_ms - (t - start_ms)) > _SNAP_WARNING_MS for slot, (t, _) in zip(natural, points_ms)):
        warnings.append(f"{label} curve points snap to {slot_ms:.0f} ms steps on this {length / 1000:.1f} s effect")
    if len(set(slots)) < len(slots):
        warnings.append(f"{label} points closer than one curve slot ({slot_ms:.0f} ms) were merged")
    return [(slot / CURVE_SLOTS, by_slot[slot]) for slot in sorted(by_slot)], warnings


def custom_curve_string(name: str, minimum: float, maximum: float, points: list[tuple[float, float]]) -> str:
    """The value part of an xLights Custom curve setting; the caller prefixes the ``C_VALUECURVE_``/``E_VALUECURVE_`` key."""
    values = ";".join(f"{x:.3f}:{(level - minimum) / (maximum - minimum):.4f}" for x, level in points)
    return f"Active=TRUE|Id=ID_VALUECURVE_{name}|Type=Custom|Min={minimum:.2f}|Max={maximum:.2f}|RV=TRUE|Values={values}|"


def _ordered_slots(natural: list[int], times: list[float]) -> list[int]:
    """Slots that never go backwards, with a step's second point one slot after its first (the last two slots at the end)."""
    slots: list[int] = []
    for i, slot in enumerate(natural):
        after_step = i > 0 and times[i] == times[i - 1]
        slots.append(min(max(slot, slots[-1] + int(after_step) if slots else slot), CURVE_SLOTS))
    for i in range(len(slots) - 2, -1, -1):
        slots[i] = min(slots[i], slots[i + 1] - int(times[i] == times[i + 1]))
    return slots


def _clipped_to(points: list[tuple[float, float]], end: float) -> list[tuple[float, float]]:
    kept = [p for p in points if p[0] <= end]
    if len(kept) == len(points) or kept and kept[-1][0] == end:
        return kept
    after_t, after_level = points[len(kept)]
    if not kept:
        return [(end, after_level)]
    before_t, before_level = kept[-1]
    level = before_level + (after_level - before_level) * (end - before_t) / (after_t - before_t)
    return [*kept, (end, level)]
