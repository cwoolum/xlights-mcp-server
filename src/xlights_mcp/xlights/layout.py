"""Suggested sequencing tiers for a show's model groups.

wash: broad parent groups that lay down a base (e.g. All, House).
feature: top-level props that carry motion (e.g. Roof Edges, Pipes, Lanterns).
skip: empty, preview-only, submodel-row, single-prop, or sub-parts of a feature.
Every group stays usable by name; tiers are suggestions. Rules are in
docs/superpowers/specs/2026-09-28-group-sequencing-design.md, "Tiers".
"""

from __future__ import annotations

from typing import Literal

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
        big_children = [c for c in g.child_groups if len(by_name[c].leaf_models) >= 2]
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

    candidates = [g for g in show.model_groups if g.name not in result and len(g.leaf_models) >= 2]
    for g in show.model_groups:
        if g.name in result:
            continue
        if len(g.leaf_models) < 2:
            result[g.name] = ("skip", "single prop")
            continue
        parent = _smallest_superset(g, candidates)
        if parent is not None:
            result[g.name] = ("skip", f"part of {parent.name}")
        else:
            result[g.name] = ("feature", f"top-level, {len(g.leaf_models)} props")
    return result


def _smallest_superset(group: ModelGroup, candidates: list[ModelGroup]) -> ModelGroup | None:
    leaves = set(group.leaf_models)
    supersets = [c for c in candidates if c.name != group.name and leaves < set(c.leaf_models)]
    return min(supersets, key=lambda c: (len(c.leaf_models), c.name), default=None)
