"""Suggested sequencing tiers for a show's model groups.

wash: broad parent groups that lay down a base (e.g. All, House).
feature: top-level props that carry motion (e.g. Roof Edges, Pipes, Lanterns).
skip: empty, preview-only, submodel-row, single-prop, or sub-parts of a feature.
Every group stays usable by name; tiers are suggestions. Rules are in
docs/superpowers/specs/2026-09-28-group-sequencing-design.md, "Tiers".
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from xlights_mcp.xlights.models import ModelGroup, ShowConfig

Tier = Literal["wash", "feature", "skip"]
TIERS: tuple[Tier, ...] = ("wash", "feature", "skip")

WASH_MIN_CHILD_GROUPS = 2
WASH_MIN_DISPLAY_SHARE = 0.8


def classify_groups(
    show: ShowConfig, overrides: dict[str, Tier] | None = None
) -> dict[str, tuple[Tier, str]]:
    """Tier and one-line reason for every group, first matching rule wins."""
    overrides = overrides or {}
    by_name = {g.name: g for g in show.model_groups}
    display_size = sum(1 for m in show.models if not m.is_placeholder)
    result: dict[str, tuple[Tier, str]] = {}

    for g in show.model_groups:
        leaves = len(g.leaf_models)
        big_children = [c for c in g.child_groups if (child := by_name.get(c)) and len(child.leaf_models) >= 2]
        share = leaves / display_size if display_size else 0.0
        if g.name in overrides:
            result[g.name] = (overrides[g.name], "override")
        elif leaves == 0:
            result[g.name] = ("skip", "empty")
        elif "preview" in g.name.lower():
            result[g.name] = ("skip", "preview-only")
        elif g.has_submodels:
            result[g.name] = ("skip", "submodel group")
        elif len(big_children) >= WASH_MIN_CHILD_GROUPS or share >= WASH_MIN_DISPLAY_SHARE:
            result[g.name] = ("wash", f"{len(big_children)} child groups, {share:.0%} of display")

    candidates = [
        g
        for g in show.model_groups
        if len(g.leaf_models) >= 2 and (g.name not in result or overrides.get(g.name) == "feature")
    ]
    for g in show.model_groups:
        if g.name in result:
            continue
        if len(g.leaf_models) < 2:
            result[g.name] = ("skip", "single prop")
            continue
        parent = _smallest_superset(g, candidates)
        twin = _first_named_twin(g, candidates)
        if parent is not None:
            result[g.name] = ("skip", f"part of {parent.name}")
        elif twin is not None:
            result[g.name] = ("skip", f"same props as {twin.name}")
        else:
            result[g.name] = ("feature", f"top-level, {len(g.leaf_models)} props")
    return result


def _name_order(group: ModelGroup) -> tuple[str, str]:
    return (group.name.lower(), group.name)


def _smallest_superset(group: ModelGroup, candidates: list[ModelGroup]) -> ModelGroup | None:
    leaves = set(group.leaf_models)
    supersets = [c for c in candidates if c.name != group.name and leaves < set(c.leaf_models)]
    return min(supersets, key=lambda c: (len(c.leaf_models), *_name_order(c)), default=None)


def _first_named_twin(group: ModelGroup, candidates: list[ModelGroup]) -> ModelGroup | None:
    leaves = set(group.leaf_models)
    twins = [
        c
        for c in candidates
        if c.name != group.name and leaves == set(c.leaf_models) and _name_order(c) < _name_order(group)
    ]
    return min(twins, key=_name_order, default=None)


OVERRIDE_FILE = "xlights-mcp.json"
ACCENT_MAX_PROPS = 8


class GroupLayout(BaseModel):
    name: str
    tier: Tier
    reason: str
    child_groups: list[str]
    parent_groups: list[str]
    prop_count: int
    y_range: tuple[float, float] | None
    accent_props: list[str]


def load_tier_overrides(show_path: Path) -> tuple[dict[str, Tier], list[str]]:
    """Tier overrides from the show's xlights-mcp.json, plus warnings for bad entries."""
    path = show_path / OVERRIDE_FILE
    if not path.exists():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return {}, [f"Ignoring {OVERRIDE_FILE}: {e}"]
    tiers = data.get("tiers", {}) if isinstance(data, dict) else None
    if not isinstance(tiers, dict):
        return {}, [f"Ignoring {OVERRIDE_FILE}: expected {{\"tiers\": {{group: tier}}}}"]

    overrides: dict[str, Tier] = {}
    warnings: list[str] = []
    for name, tier in tiers.items():
        normalized = tier.strip().lower() if isinstance(tier, str) else None
        if normalized in TIERS:
            overrides[name] = normalized
        else:
            warnings.append(f"{OVERRIDE_FILE}: group '{name}' has unknown tier '{tier}' (use {', '.join(TIERS)})")
    return overrides, warnings


def build_show_layout(show: ShowConfig, show_path: Path) -> dict[str, Any]:
    """The get_show_layout payload: tiers, hierarchy, heights, accent props, warnings."""
    overrides, warnings = load_tier_overrides(show_path)
    names = {g.name for g in show.model_groups}
    for name in overrides:
        if name not in names:
            warnings.append(f"{OVERRIDE_FILE}: no group named '{name}'")
    overrides = {n: t for n, t in overrides.items() if n in names}
    tiers = classify_groups(show, overrides)
    for g in show.model_groups:
        if overrides.get(g.name) == "feature" and not g.leaf_models:
            warnings.append(f"{g.name} is overridden to feature but has no props")

    height = {m.name: m.world_pos_y for m in show.models}
    rows = []
    for g in show.model_groups:
        tier, reason = tiers[g.name]
        ys = [y for m in g.leaf_models if (y := height.get(m)) is not None and math.isfinite(y)]
        rows.append(
            GroupLayout(
                name=g.name,
                tier=tier,
                reason=reason,
                child_groups=g.child_groups,
                parent_groups=g.parent_groups,
                prop_count=len(g.leaf_models),
                y_range=(round(min(ys), 1), round(max(ys), 1)) if ys else None,
                accent_props=g.leaf_models if tier == "feature" and len(g.leaf_models) <= ACCENT_MAX_PROPS else [],
            )
        )
    rows.sort(key=lambda r: (TIERS.index(r.tier), r.name.lower()))

    real = [m.name for m in show.models if not m.is_placeholder]
    grouped = {leaf for g in show.model_groups for leaf in g.leaf_models}
    return {
        "show": show.show_name,
        "model_count": len(real),
        "placeholder_count": len(show.models) - len(real),
        "groups": [r.model_dump(mode="json") for r in rows],
        "ungrouped_models": sorted(n for n in real if n not in grouped),
        "warnings": [*show.warnings, *warnings],
    }
