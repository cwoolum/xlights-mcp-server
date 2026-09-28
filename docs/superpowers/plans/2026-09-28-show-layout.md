# Show Layout (Group-Aware Sequencing, PR 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse the show's model groups correctly (nested, placeholders excluded), classify them into wash/feature/skip tiers with an optional per-show override, and expose that through a new `get_show_layout` MCP tool.

**Architecture:** `xlights/models.py` gains placeholder detection, `LightModel.world_pos_y`, resolved `ModelGroup` fields and `ShowConfig.warnings`. `xlights/show.py` reads groups from `<modelGroups>` (and the legacy location inside `<models>`), dedupes names and resolves nesting. A new `xlights/layout.py` owns tier rules, the override file and the `get_show_layout` payload. `server.py` adds the tool and a `list_models` placeholder filter; `engine.py`'s group detection switches to feature-tier groups so `create_sequence` stops treating `All` as a group until PR 3 replaces it.

**Tech Stack:** Python 3.12, pydantic v2, `xml.etree.ElementTree`, mcp 1.x (FastMCP), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-28-group-sequencing-design.md` — sections "Show layout" and "Delivery" (this plan is PR 1). Read them before starting.

---

## Conventions for every task

- Working dir `E:\xlights-mcp-server`, branch `feat/group-sequencing`. Shell: Git Bash.
- Python: always `.venv/Scripts/python`, never bare `python`. Never run `uv run`, `uv sync` or `uv pip install` (the venv has hand-installed CUDA torch, demucs and madmom).
- One test: `.venv/Scripts/python -m pytest tests/<file>.py::<test> -v`. Full suite: `.venv/Scripts/python -m pytest -q` (~15 s, currently 262 passed, 1 deselected).
- Lint: `.venv/Scripts/python -m ruff check <files you created or changed>`. New files must be clean; in modified files fix findings only on lines you touched.
- Test imports go in the top import block, sorted.
- Comments only where the *why* isn't obvious.
- Commit only the files the task names (`git add <paths>`; never `git commit -a` or `git add .`). Commit trailer: `Co-Authored-By:` naming yourself.

## File map

| File | Status | Responsibility |
|---|---|---|
| `src/xlights_mcp/xlights/models.py` | modify | `is_placeholder_name`, `LightModel.world_pos_y` + `is_placeholder`, resolved `ModelGroup` fields, `ShowConfig.warnings` |
| `src/xlights_mcp/xlights/show.py` | modify | read `WorldPosY`; group parsing from both locations, dedupe, nesting; `load_show_config` fills warnings |
| `src/xlights_mcp/xlights/layout.py` | create | tier rules, override file, `build_show_layout` payload |
| `src/xlights_mcp/server.py` | modify | `get_show_layout` tool; `list_models(include_placeholders=False)` |
| `src/xlights_mcp/sequencer/engine.py` | modify | `_detect_model_groups` uses feature-tier groups |
| `README.md` | modify | tool table |
| `tests/fixtures/show_groups/xlights_rgbeffects.xml` | create | fixture show |
| `tests/test_show_groups.py`, `tests/test_layout.py`, `tests/test_show_tools.py`, `tests/test_engine_groups.py` | create | tests |

## The fixture show (used by every task)

26 real models, 2 placeholders. Expected results, derived from the spec's rules, are stated in the tests.

| Group | Members | Expected tier (reason) |
|---|---|---|
| `All` | House, Pipes, Lanterns | wash (3 child groups) |
| `House` | Roof Edges, Door | wash (2 child groups) |
| `Everything Flat` | every real model except `Tree 6ft`, plus one placeholder | wash (96% of display) |
| `Roof Edges` | Roof Left, Roof Right, `Roof Mid - Null - Do Not Map`, Under Roof | feature (4 props) |
| `Under Roof` | Under Left, Under Right | skip (part of Roof Edges) |
| `Door` | Door L, Door R — and a duplicate `Door` definition later | feature (2 props) |
| `Pipes` | Pipe 1 … Pipe 14 (54% of display, no child groups) | feature (14 props) |
| `Pipes-Odd` | Pipe 1, 3, … 13 | skip (part of Pipes) |
| `Pipe Rows` | `Pipe 1/Top`, `Pipe 2/Top` | skip (submodel group) |
| `Lanterns` | Lantern1–3 | feature (3 props) |
| `Legacy Arches` (inside `<models>`) | Arch 1, Arch 2 | feature (2 props) |
| `Empty` | — | skip (empty) |
| `PreviewONLY All` | Roof Left, Door L | skip (preview) |
| `Single` | Lantern1 | skip (single prop) |
| `Cycle A` / `Cycle B` | each other (+ Door L in B) | skip (single prop) |

Ungrouped real models: `Tree 6ft`. Accent props: Roof Edges (4), Door (2), Lanterns (3), Legacy Arches (2).

---

### Task 1: Fixture show, placeholders, model height

**Files:**
- Create: `tests/fixtures/show_groups/xlights_rgbeffects.xml`
- Modify: `src/xlights_mcp/xlights/models.py`
- Modify: `src/xlights_mcp/xlights/show.py` (`load_show_models`)
- Create: `tests/test_show_groups.py`

- [ ] **Step 1: Create the fixture** `tests/fixtures/show_groups/xlights_rgbeffects.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<xrgb>
  <models>
    <model name="Roof Left" DisplayAs="Single Line" WorldPosY="150.0"/>
    <model name="Roof Right" DisplayAs="Single Line" WorldPosY="150.0"/>
    <model name="Roof Mid - Null - Do Not Map" DisplayAs="Single Line" WorldPosY="150.0"/>
    <model name="Under Left" DisplayAs="Single Line" WorldPosY="120.0"/>
    <model name="Under Right" DisplayAs="Single Line" WorldPosY="120.0"/>
    <model name="Door L" DisplayAs="Single Line" WorldPosY="20.0"/>
    <model name="Door R" DisplayAs="Single Line" WorldPosY="20.0"/>
    <model name="Pipe 1" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 2" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 3" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 4" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 5" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 6" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 7" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 8" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 9" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 10" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 11" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 12" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 13" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Pipe 14" DisplayAs="Single Line" WorldPosY="5.0"/>
    <model name="Lantern1" DisplayAs="Custom" WorldPosY="90.0"/>
    <model name="Lantern2" DisplayAs="Custom" WorldPosY="100.0"/>
    <model name="Lantern3" DisplayAs="Custom" WorldPosY="110.0"/>
    <model name="Arch 1" DisplayAs="Arches" WorldPosY="10.0"/>
    <model name="Arch 2" DisplayAs="Arches" WorldPosY="10.0"/>
    <model name="Tree 6ft" DisplayAs="Tree 360" WorldPosY="40.0"/>
    <model name="Spare - Dont Map" DisplayAs="Single Line"/>
    <modelGroup name="Legacy Arches" models="Arch 1,Arch 2"/>
  </models>
  <modelGroups>
    <modelGroup name="All" models="House,Pipes,Lanterns"/>
    <modelGroup name="House" models="Roof Edges,Door"/>
    <modelGroup name="Everything Flat" models="Roof Left,Roof Right,Under Left,Under Right,Door L,Door R,Pipe 1,Pipe 2,Pipe 3,Pipe 4,Pipe 5,Pipe 6,Pipe 7,Pipe 8,Pipe 9,Pipe 10,Pipe 11,Pipe 12,Pipe 13,Pipe 14,Lantern1,Lantern2,Lantern3,Arch 1,Arch 2,Spare - Dont Map"/>
    <modelGroup name="Roof Edges" models="Roof Left,Roof Right,Roof Mid - Null - Do Not Map,Under Roof"/>
    <modelGroup name="Under Roof" models="Under Left,Under Right"/>
    <modelGroup name="Door" models="Door L,Door R"/>
    <modelGroup name="Pipes" models="Pipe 1,Pipe 2,Pipe 3,Pipe 4,Pipe 5,Pipe 6,Pipe 7,Pipe 8,Pipe 9,Pipe 10,Pipe 11,Pipe 12,Pipe 13,Pipe 14"/>
    <modelGroup name="Pipes-Odd" models="Pipe 1,Pipe 3,Pipe 5,Pipe 7,Pipe 9,Pipe 11,Pipe 13"/>
    <modelGroup name="Pipe Rows" models="Pipe 1/Top,Pipe 2/Top"/>
    <modelGroup name="Lanterns" models="Lantern1,Lantern2,Lantern3"/>
    <modelGroup name="Empty" models=""/>
    <modelGroup name="PreviewONLY All" models="Roof Left,Door L"/>
    <modelGroup name="Single" models="Lantern1"/>
    <modelGroup name="Cycle A" models="Cycle B"/>
    <modelGroup name="Cycle B" models="Cycle A,Door L"/>
    <modelGroup name="Door" models="Door L"/>
  </modelGroups>
</xrgb>
```

- [ ] **Step 2: Write failing tests** in `tests/test_show_groups.py`:

```python
"""Show parsing: placeholders, model height, model groups."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.xlights.models import ModelGroup, is_placeholder_name
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
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_show_groups.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_placeholder_name'`

- [ ] **Step 4: Implement.** In `models.py` add `import re` to the imports, then above `class Controller`:

```python
_PLACEHOLDER_NAME = re.compile(r"d(?:on'?t|o not) map", re.IGNORECASE)


def is_placeholder_name(name: str) -> bool:
    """True for layout-only placeholder models ("Dont Map", "Don't Map", "Do Not Map")."""
    return bool(_PLACEHOLDER_NAME.search(name))
```

In `LightModel`, after `face_definitions`:

```python
    world_pos_y: float | None = None  # height in the layout (WorldPosY)

    @property
    def is_placeholder(self) -> bool:
        return is_placeholder_name(self.name)
```

(Place the property next to the existing `model_category` property.)

In `show.py` `load_show_models`, add to the `LightModel(...)` call:

```python
                world_pos_y=_float_or_none(m.get("WorldPosY")),
```

and add this helper at the bottom of `show.py`:

```python
def _float_or_none(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_show_groups.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/show_groups/xlights_rgbeffects.xml tests/test_show_groups.py src/xlights_mcp/xlights/models.py src/xlights_mcp/xlights/show.py
git commit -m "Detect placeholder models and read model height"
```

---

### Task 2: Parse groups from both locations, dedupe, resolve nesting

**Files:**
- Modify: `src/xlights_mcp/xlights/models.py` (`ModelGroup`, `ShowConfig`)
- Modify: `src/xlights_mcp/xlights/show.py` (`load_show_config`, `load_model_groups`)
- Modify: `tests/test_show_groups.py`

- [ ] **Step 1: Add failing tests** to `tests/test_show_groups.py` (add `load_model_groups, load_show_config` to the `xlights_mcp.xlights.show` import):

```python
def _groups():
    return {g.name: g for g in load_show_config(SHOW).model_groups}


def test_groups_come_from_modelgroups_and_the_legacy_models_section():
    groups = _groups()

    assert "All" in groups and "Legacy Arches" in groups
    assert len(groups) == 16  # 17 definitions, one duplicate


def test_duplicate_group_name_keeps_first_definition_and_warns():
    show = load_show_config(SHOW)
    door = next(g for g in show.model_groups if g.name == "Door")

    assert door.members == ["Door L", "Door R"]
    assert any("'Door'" in w and "more than once" in w for w in show.warnings)


def test_nested_groups_resolve_to_real_leaf_models():
    groups = _groups()

    assert groups["Roof Edges"].leaf_models == ["Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert groups["House"].leaf_models == ["Door L", "Door R", "Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert groups["Empty"].leaf_models == []


def test_child_and_parent_groups():
    groups = _groups()

    assert groups["Roof Edges"].child_groups == ["Under Roof"]
    assert groups["Under Roof"].parent_groups == ["Roof Edges"]
    assert groups["House"].parent_groups == ["All"]


def test_submodel_members_map_to_their_parent_model():
    rows = _groups()["Pipe Rows"]

    assert rows.has_submodels is True
    assert rows.leaf_models == ["Pipe 1", "Pipe 2"]


def test_group_cycles_terminate():
    groups = _groups()

    assert groups["Cycle A"].leaf_models == ["Door L"]
    assert groups["Cycle B"].leaf_models == ["Door L"]


def test_load_model_groups_returns_resolved_groups():
    groups = {g.name: g for g in load_model_groups(SHOW)}

    assert groups["House"].child_groups == ["Roof Edges", "Door"]


def test_model_group_still_constructs_with_name_and_members_only():
    group = ModelGroup(name="All Arches", members=["Arch 1"])

    assert group.leaf_models == [] and group.child_groups == [] and group.has_submodels is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_show_groups.py -v`
Expected: the new tests FAIL (groups missing / `AttributeError: ... has no attribute 'leaf_models'`).

- [ ] **Step 3: Implement.** In `models.py`, replace the body of `ModelGroup` with:

```python
class ModelGroup(BaseModel):
    """A group of models that can be controlled together."""

    name: str
    members: list[str] = Field(default_factory=list)  # direct members as written in the file
    child_groups: list[str] = Field(default_factory=list)  # direct members that are groups
    parent_groups: list[str] = Field(default_factory=list)  # groups listing this one as a member
    leaf_models: list[str] = Field(default_factory=list)  # real models reached through nesting, sorted
    has_submodels: bool = False  # some direct member is a submodel ("Model/Sub")
    grid_size: str = ""
    layout: str = ""
```

In `ShowConfig`, after `total_channels`:

```python
    warnings: list[str] = Field(default_factory=list)
```

In `show.py`, replace `load_show_config` and `load_model_groups` with:

```python
def load_show_config(show_path: Path) -> ShowConfig:
    """Load complete show configuration from an xLights show folder.

    Reads xlights_networks.xml and xlights_rgbeffects.xml to build
    a complete picture of the controllers, models, and groups.
    """
    controllers = load_show_controllers(show_path)
    models = load_show_models(show_path)
    groups, warnings = _load_groups(show_path, models)

    return ShowConfig(
        show_path=str(show_path),
        show_name=show_path.name,
        controllers=controllers,
        models=models,
        model_groups=groups,
        total_channels=sum(c.max_channels for c in controllers),
        warnings=warnings,
    )


def load_model_groups(show_path: Path) -> list[ModelGroup]:
    """Parse and resolve model groups from xlights_rgbeffects.xml."""
    groups, _ = _load_groups(show_path, load_show_models(show_path))
    return groups


def _load_groups(show_path: Path, models: list[LightModel]) -> tuple[list[ModelGroup], list[str]]:
    effects_file = show_path / "xlights_rgbeffects.xml"
    if not effects_file.exists():
        return [], []
    root = ET.parse(effects_file).getroot()

    # xLights keeps groups in <modelGroups>; older files put them inside <models>.
    elements = []
    for container in ("modelGroups", "models"):
        parent = root.find(container)
        if parent is not None:
            elements.extend(e for e in parent if e.tag == "modelGroup")

    warnings: list[str] = []
    groups: dict[str, ModelGroup] = {}
    for e in elements:
        name = e.get("name", "")
        if not name:
            continue
        if name in groups:
            warnings.append(f"Group '{name}' is defined more than once; using the first definition")
            continue
        groups[name] = ModelGroup(
            name=name,
            members=[n.strip() for n in e.get("models", "").split(",") if n.strip()],
            grid_size=e.get("GridSize", ""),
            layout=e.get("layout", ""),
        )

    real_models = {m.name for m in models if not m.is_placeholder}
    for g in groups.values():
        g.child_groups = [m for m in g.members if m in groups]
        g.has_submodels = any("/" in m for m in g.members)
    for g in groups.values():
        g.parent_groups = sorted(p.name for p in groups.values() if g.name in p.child_groups)
        g.leaf_models = sorted(_leaf_models(g.name, groups, real_models, ()))

    logger.info(f"Loaded {len(groups)} model groups from {effects_file}")
    return list(groups.values()), warnings


def _leaf_models(
    name: str, groups: dict[str, ModelGroup], real_models: set[str], path: tuple[str, ...]
) -> set[str]:
    if name in path:  # a group nested inside itself
        return set()
    leaves: set[str] = set()
    for member in groups[name].members:
        if member in groups:
            leaves |= _leaf_models(member, groups, real_models, (*path, name))
        else:
            model = member.split("/", 1)[0]  # submodels count as their parent model
            if model in real_models:
                leaves.add(model)
    return leaves
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_show_groups.py tests/test_matcher.py tests/test_remap_integration.py -v`
Expected: all pass (the remapper tests confirm the legacy `<models>` location still works).

- [ ] **Step 5: Full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass. If a test outside this task fails because groups are now parsed (e.g. the engine now sees groups), stop and report it — Task 6 handles the engine.

- [ ] **Step 6: Commit**

```bash
git add src/xlights_mcp/xlights/models.py src/xlights_mcp/xlights/show.py tests/test_show_groups.py
git commit -m "Read model groups from <modelGroups> and resolve nesting"
```

---

### Task 3: Tier classification

**Files:**
- Create: `src/xlights_mcp/xlights/layout.py`
- Create: `tests/test_layout.py`

- [ ] **Step 1: Write failing tests** in `tests/test_layout.py`:

```python
"""Group tiers and the get_show_layout payload."""

from __future__ import annotations

from pathlib import Path

from xlights_mcp.xlights.layout import classify_groups
from xlights_mcp.xlights.show import load_show_config

SHOW = Path(__file__).parent / "fixtures" / "show_groups"

EXPECTED = {
    "All": "wash",
    "House": "wash",
    "Everything Flat": "wash",
    "Roof Edges": "feature",
    "Door": "feature",
    "Pipes": "feature",
    "Lanterns": "feature",
    "Legacy Arches": "feature",
    "Under Roof": "skip",
    "Pipes-Odd": "skip",
    "Pipe Rows": "skip",
    "Empty": "skip",
    "PreviewONLY All": "skip",
    "Single": "skip",
    "Cycle A": "skip",
    "Cycle B": "skip",
}


def test_every_group_gets_the_expected_tier():
    tiers = classify_groups(load_show_config(SHOW))

    assert {name: tier for name, (tier, _) in tiers.items()} == EXPECTED


def test_reasons_explain_the_rule():
    tiers = classify_groups(load_show_config(SHOW))

    assert tiers["Empty"][1] == "empty"
    assert tiers["PreviewONLY All"][1] == "preview-only"
    assert tiers["Pipe Rows"][1] == "submodel group"
    assert tiers["Single"][1] == "single prop"
    assert tiers["Under Roof"][1] == "part of Roof Edges"
    assert tiers["Pipes-Odd"][1] == "part of Pipes"
    assert tiers["Roof Edges"][1] == "top-level, 4 props"
    assert tiers["House"][1] == "2 child groups, 23% of display"
    assert tiers["Everything Flat"][1] == "0 child groups, 96% of display"


def test_large_group_without_child_groups_stays_a_feature():
    # Pipes holds 14 of 26 props but has no child groups, like the Halloween show's Pipes.
    tiers = classify_groups(load_show_config(SHOW))

    assert tiers["Pipes"] == ("feature", "top-level, 14 props")


def test_override_wins():
    tiers = classify_groups(load_show_config(SHOW), overrides={"Pipes-Odd": "feature", "All": "skip"})

    assert tiers["Pipes-Odd"] == ("feature", "override")
    assert tiers["All"] == ("skip", "override")
```

(Percentages: House has 6 of 26 display props → 23%; Everything Flat 25 of 26 → 96%.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_layout.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xlights_mcp.xlights.layout'`

- [ ] **Step 3: Implement** `src/xlights_mcp/xlights/layout.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_layout.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/xlights/layout.py tests/test_layout.py
git commit -m "Classify model groups into wash, feature and skip tiers"
```

---

### Task 4: Override file and the layout payload

**Files:**
- Modify: `src/xlights_mcp/xlights/layout.py`
- Modify: `tests/test_layout.py`

- [ ] **Step 1: Add failing tests** to `tests/test_layout.py` (add `import json`, `import shutil` at the top, and `build_show_layout, load_tier_overrides` to the layout import):

```python
def _show_copy(tmp_path: Path, overrides: object | None = None, raw: str | None = None) -> Path:
    show = tmp_path / "show"
    show.mkdir()
    shutil.copy(SHOW / "xlights_rgbeffects.xml", show / "xlights_rgbeffects.xml")
    if raw is not None:
        (show / "xlights-mcp.json").write_text(raw, encoding="utf-8")
    elif overrides is not None:
        (show / "xlights-mcp.json").write_text(json.dumps(overrides), encoding="utf-8")
    return show


def test_no_override_file_means_no_overrides(tmp_path):
    assert load_tier_overrides(_show_copy(tmp_path)) == ({}, [])


def test_override_file_invalid_tier_is_ignored_with_warning(tmp_path):
    show = _show_copy(tmp_path, {"tiers": {"Pipes-Odd": "feature", "Door": "sparkly"}})

    overrides, warnings = load_tier_overrides(show)

    assert overrides == {"Pipes-Odd": "feature"}
    assert any("'Door'" in w and "sparkly" in w for w in warnings)


def test_override_file_bad_json_warns(tmp_path):
    overrides, warnings = load_tier_overrides(_show_copy(tmp_path, raw="{not json"))

    assert overrides == {}
    assert warnings and "xlights-mcp.json" in warnings[0]


def test_layout_payload(tmp_path):
    show = _show_copy(tmp_path, {"tiers": {"Pipes-Odd": "feature", "Nope": "skip"}})

    layout = build_show_layout(load_show_config(show), show)
    groups = {g["name"]: g for g in layout["groups"]}

    assert layout["model_count"] == 26
    assert layout["placeholder_count"] == 2
    assert layout["ungrouped_models"] == ["Tree 6ft"]
    assert [g["tier"] for g in layout["groups"]] == sorted(
        (g["tier"] for g in layout["groups"]), key=["wash", "feature", "skip"].index
    )
    assert groups["Pipes-Odd"]["tier"] == "feature"
    assert groups["Roof Edges"]["accent_props"] == ["Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert groups["Pipes"]["accent_props"] == []
    assert groups["Under Roof"]["accent_props"] == []
    assert groups["Roof Edges"]["y_range"] == [120.0, 150.0]
    assert groups["Roof Edges"]["prop_count"] == 4
    assert groups["Roof Edges"]["parent_groups"] == ["House"]
    assert groups["Empty"]["y_range"] is None
    assert any("'Nope'" in w for w in layout["warnings"])
    assert any("'Door'" in w and "more than once" in w for w in layout["warnings"])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_layout.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_show_layout'`

- [ ] **Step 3: Implement** — append to `layout.py` (add `import json`, `from pathlib import Path`, `from typing import Any` and `from pydantic import BaseModel` to the imports):

```python
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
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {}, [f"Ignoring {OVERRIDE_FILE}: {e}"]
    tiers = data.get("tiers", {}) if isinstance(data, dict) else None
    if not isinstance(tiers, dict):
        return {}, [f"Ignoring {OVERRIDE_FILE}: expected {{\"tiers\": {{group: tier}}}}"]

    overrides: dict[str, Tier] = {}
    warnings: list[str] = []
    for name, tier in tiers.items():
        if tier in TIERS:
            overrides[name] = tier
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

    height = {m.name: m.world_pos_y for m in show.models}
    rows = []
    for g in show.model_groups:
        tier, reason = tiers[g.name]
        ys = [height[m] for m in g.leaf_models if height.get(m) is not None]
        rows.append(
            GroupLayout(
                name=g.name,
                tier=tier,
                reason=reason,
                child_groups=g.child_groups,
                parent_groups=g.parent_groups,
                prop_count=len(g.leaf_models),
                y_range=(min(ys), max(ys)) if ys else None,
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
```

(`model_dump(mode="json")` renders the `y_range` tuple as a list, which the test compares against.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_layout.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/xlights/layout.py tests/test_layout.py
git commit -m "Add tier override file and the show layout payload"
```

---

### Task 5: MCP tools — `get_show_layout`, `list_models` placeholder filter

**Files:**
- Modify: `src/xlights_mcp/server.py` (`list_models` ~line 186; new tool after it)
- Create: `tests/test_show_tools.py`

- [ ] **Step 1: Write failing tests** in `tests/test_show_tools.py`:

```python
"""get_show_layout and list_models through an in-memory MCP session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


@pytest.fixture
def fixture_show(monkeypatch: pytest.MonkeyPatch) -> ServerConfig:
    config = ServerConfig(show_folders={"fixture": str(SHOW)}, active_show="fixture")
    monkeypatch.setattr(server_module, "_config", config)
    return config


async def _call(name: str, args: dict) -> dict:
    async with create_connected_server_and_client_session(server_module.mcp) as client:
        result = await client.call_tool(name, args)
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


async def test_get_show_layout_for_the_active_show(fixture_show):
    layout = await _call("get_show_layout", {})

    tiers = {g["name"]: g["tier"] for g in layout["groups"]}
    assert layout["show"] == "fixture"
    assert tiers["House"] == "wash" and tiers["Pipes"] == "feature" and tiers["Pipe Rows"] == "skip"


async def test_get_show_layout_by_name(fixture_show):
    layout = await _call("get_show_layout", {"show_name": "fixture"})

    assert layout["show"] == "fixture"


async def test_get_show_layout_unknown_show(fixture_show):
    payload = await _call("get_show_layout", {"show_name": "nope"})

    assert "error" in payload


async def test_list_models_hides_placeholders_by_default(fixture_show):
    default = await _call("list_models", {})
    everything = await _call("list_models", {"include_placeholders": True})

    names = {m["name"] for m in default["models"]}
    assert "Spare - Dont Map" not in names and "Roof Left" in names
    assert default["model_count"] == 26
    assert everything["model_count"] == 28
```

(`ServerConfig` field names: check `src/xlights_mcp/config.py` — it has `show_folders` and `active_show`. If constructing it touches the user's real config file or auto-detection, report NEEDS_CONTEXT rather than working around it.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_show_tools.py -v`
Expected: FAIL (unknown tool `get_show_layout`; `include_placeholders` not accepted).

- [ ] **Step 3: Implement.** Replace `list_models` in `server.py` with:

```python
@mcp.tool()
def list_models(include_placeholders: bool = False) -> dict:
    """List all light models in the active xLights show.

    Returns model names, types, controller assignments, and channel info.
    Layout-only placeholder models ("Dont Map", "Do Not Map") are hidden unless
    include_placeholders is true. Use get_show_layout for groups and tiers.
    """
    from xlights_mcp.xlights.show import load_show_models

    config = get_config()
    show_path = config.active_show_path
    if not show_path or not show_path.exists():
        return {
            "error": "No active show folder configured.",
            "action_required": "Ask the user for the path to their xLights show directory and call add_show_folder.",
        }

    models = [m for m in load_show_models(show_path) if include_placeholders or not m.is_placeholder]
    return {
        "show": config.active_show,
        "model_count": len(models),
        "models": [m.model_dump() for m in models],
    }


@mcp.tool()
def get_show_layout(show_name: str | None = None) -> dict:
    """Get the show's model groups with a suggested sequencing tier for each.

    Tiers: "wash" = broad parent groups for a base layer (e.g. All, House);
    "feature" = top-level props that carry motion (e.g. Roof Edges, Pipes);
    "skip" = empty, preview-only, submodel-row, single-prop groups, or sub-parts
    of a feature. Every group is still usable by name. Each group lists its child
    and parent groups, prop count, height range (y_range) and, for small feature
    groups, accent_props (single props for accents). Tiers can be overridden in
    xlights-mcp.json in the show folder: {"tiers": {"Group Name": "feature"}}.

    Args:
        show_name: Show to describe (defaults to the active show)
    """
    from xlights_mcp.xlights.layout import build_show_layout
    from xlights_mcp.xlights.show import load_show_config

    config = get_config()
    if show_name:
        resolved = _resolve_show(config, show_name)
        if isinstance(resolved, dict):
            return resolved
        show_path = resolved
    else:
        show_path = config.active_show_path
        if not show_path or not show_path.exists():
            return {
                "error": "No active show folder configured.",
                "action_required": "Ask the user for the path to their xLights show directory and call add_show_folder.",
            }

    layout = build_show_layout(load_show_config(show_path), show_path)
    layout["show"] = show_name or config.active_show
    return layout
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_show_tools.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/server.py tests/test_show_tools.py
git commit -m "Add get_show_layout tool and hide placeholder models by default"
```

---

### Task 6: Engine uses feature-tier groups

Now that groups parse, the old engine would treat `All` (every model) as one group. Until PR 3 replaces the engine, its group detection uses feature-tier groups only.

**Files:**
- Modify: `src/xlights_mcp/sequencer/engine.py` (`_detect_model_groups`, Strategy 1, ~lines 350–367)
- Create: `tests/test_engine_groups.py`

- [ ] **Step 1: Write the failing test** in `tests/test_engine_groups.py`:

```python
"""create_sequence's legacy engine groups models by feature-tier groups."""

from __future__ import annotations

from pathlib import Path

from xlights_mcp.sequencer.engine import _detect_model_groups
from xlights_mcp.xlights.show import load_show_config

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


def test_engine_groups_are_the_feature_tier_groups():
    show = load_show_config(SHOW)

    groups, ungrouped, _ = _detect_model_groups(show.models, show)

    assert set(groups) == {"Roof Edges", "Door", "Pipes", "Lanterns", "Legacy Arches"}
    assert [m.name for m in groups["Roof Edges"]] == ["Roof Left", "Roof Right", "Under Left", "Under Right"]
    assert {m.name for m in ungrouped} == {"Tree 6ft", "Roof Mid - Null - Do Not Map", "Spare - Dont Map"}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_engine_groups.py -v`
Expected: FAIL (groups include `All`, `House`, … and members aren't resolved to leaves).

- [ ] **Step 3: Implement.** In `_detect_model_groups`, replace the Strategy 1 block's loop so it reads:

```python
    # --- Strategy 1: xLights-defined feature-tier groups ---
    if show_config.model_groups:
        from xlights_mcp.xlights.layout import classify_groups

        tiers = classify_groups(show_config)
        groups: dict[str, list[LightModel]] = {}
        group_categories: dict[str, str] = {}
        grouped_names: set[str] = set()

        for mg in show_config.model_groups:
            if tiers[mg.name][0] != "feature":
                continue
            members = [model_by_name[n] for n in mg.leaf_models if n in model_by_name]
            if len(members) >= 2:
                groups[mg.name] = members
                grouped_names.update(m.name for m in members)
                cats = [m.model_category for m in members]
                group_categories[mg.name] = max(set(cats), key=cats.count)

        if groups:
            ungrouped = [m for m in models if m.name not in grouped_names]
            logger.info(f"Using {len(groups)} xLights feature-tier groups")
            return groups, ungrouped, group_categories
```

Keep Strategy 2 (prefix fallback) unchanged. Placeholders remain in `ungrouped` here; PR 3 removes this engine path.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_engine_groups.py -v` → 1 passed.
Run: `.venv/Scripts/python -m pytest -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/sequencer/engine.py tests/test_engine_groups.py
git commit -m "Group legacy engine effects by feature-tier groups"
```

---

### Task 7: README and real-show check

**Files:**
- Modify: `README.md` (tool table, ~line 275)

- [ ] **Step 1: README.** Change the `list_models` row to say placeholders are hidden by default, and add after it:

```markdown
| `get_show_layout` | Model groups with a suggested tier (wash / feature / skip), hierarchy, height range and accent props; override tiers in `xlights-mcp.json` in the show folder |
```

- [ ] **Step 2: Real-show check** (read-only; no files written):

```bash
.venv/Scripts/python - <<'PY'
from pathlib import Path
from xlights_mcp.xlights.layout import build_show_layout
from xlights_mcp.xlights.show import load_show_config
p = Path(r"E:\XLights\HalloweenShow")
layout = build_show_layout(load_show_config(p), p)
for tier in ("wash", "feature", "skip"):
    print(tier, sorted(g["name"] for g in layout["groups"] if g["tier"] == tier))
print("models", layout["model_count"], "placeholders", layout["placeholder_count"])
print("ungrouped", layout["ungrouped_models"])
print("warnings", layout["warnings"])
PY
```

Expected, exactly (spec, "Tiers"):
- wash: `All`, `House`, `Roof`
- feature: `Door`, `Entry Post`, `Lanterns`, `Pipes`, `Roof Edges`, `Spooky Fence`, `Spots`, `Tier 1-2 Mid`, `Tier 3`, `Under Window`, `Walkway`
- skip: `Lantern Center`, `Pathlights`, `Peace-Even`, `Peace-Odd`, `Peace-P1` … `Peace-P7`, `PreviewONLY All`, `Top Roof`, `Tree Spots`, `Trees`, `Under Roof`
- models 122, placeholders 6; a warning that `Trees` is defined more than once.

If anything differs, stop and report the output — do not change the rules to fit.

- [ ] **Step 3: Full suite and lint**

Run: `.venv/Scripts/python -m pytest -q`
Run: `.venv/Scripts/python -m ruff check src/xlights_mcp/xlights/layout.py tests/test_show_groups.py tests/test_layout.py tests/test_show_tools.py tests/test_engine_groups.py`
Expected: all pass; no findings in these files. For `models.py`, `show.py`, `server.py`, `engine.py`, no findings on changed lines.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document get_show_layout"
```
