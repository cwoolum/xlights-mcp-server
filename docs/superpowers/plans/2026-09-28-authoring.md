# Authoring (profile, playbook prompt, baseline) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR 3 of `docs/superpowers/specs/2026-09-28-group-sequencing-design.md`. It adds four things:
- `profile_sequence`, a style profile of a hand-made sequence;
- the `sequence_song` MCP prompt, a playbook that walks an LLM through analyse → layout → reference → plan → `write_sequence`;
- a `generated` flag in `list_sequences`;
- a rewrite of `create_sequence(mode="auto")` as a small baseline that builds a plan and writes it through PR 2's `write_plan`.

**Architecture:**
- **Profile:** `xlights/profile.py` reads an `.xsq` with ElementTree, turns each element's non-`Off` effects into merged time spans, samples concurrency every 50 ms with a numpy difference array, and measures parent/child overlap with PR 1's `contained_elements`.
- **Prompt:** the text is a Markdown template in `src/xlights_mcp/prompts/sequence_song.md`, rendered by `xlights_mcp.prompts.render_sequence_song` and registered with `@mcp.prompt()`.
- **Baseline:** `sequencer/engine.py` keeps `generate_sequence`, the guided preview and `preview_sequence_plan`. The old `_generate_auto` goes away, along with its per-model loops, prefix grouping and stem tables. In its place:
  - `build_baseline_plan(analysis, show, colors, exclude)` returns plan dicts built from `build_show_layout`;
  - the new `_generate_auto` adds singing-face placements and lyric tracks, then calls `write_plan`.

**Tech Stack:** Python 3.12, pydantic v2, FastMCP (mcp<2, `@mcp.prompt()`), numpy, `xml.etree.ElementTree`, pytest + pytest-asyncio (auto mode).

---

## Ground rules for every task

- **Branch:** `feat/authoring`, stacked on `feat/plan-writer` (PR #5), which is stacked on `feat/group-sequencing` (PR #4). Don't rebase, merge or switch branches.
- **Python:** run it as `.venv/Scripts/python` from `E:\xlights-mcp-server`. Never run `uv run`, `uv sync` or `uv pip install`.
- **Tests:** `.venv/Scripts/python -m pytest <path> -q`.
- **Commits:** stage only the files the task names (`git add <paths>`), then `git commit -m ...`. Never use `git commit -a`, `git add .`, `git add -A` or `git stash`. End each commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Editing:** prefer the Edit/Write tools. If you use a script, check the result; an earlier script once turned a regex `\b` into a backspace byte.
- **Comments:** none that restate the code. Keep docstrings short and match the surrounding style.
- **Suite:** the full suite must pass before Task 8: `.venv/Scripts/python -m pytest -q`. The baseline is 424 passed, 1 deselected.
- **Shared test helpers**, in `tests/show_fixtures.py` and `tests/conftest.py`:
  - `SHOW_GROUPS` (path to the fixture show)
  - `make_analysis(duration_s, beat_times, downbeat_times, path="Song.mp3", **fields)` → a 120 BPM `SongAnalysis`
  - `call_tool(name, args)` → the parsed JSON payload, asserting no MCP error
  - `write_xsq_stub(path, body)`
  - the fixture `show_copy`, a tmp folder holding a copy of the fixture `xlights_rgbeffects.xml`
  - the fixture `click_track`, a 3 s wav

  Look at `tests/test_write_sequence_tool.py` for how a tool test points the server at `show_copy` and caches an analysis with `save_cached`.

## File structure

| File | Change | Responsibility |
|---|---|---|
| `src/xlights_mcp/xlights/xsq_reader.py` | modify | `is_generated_file`, `latest_hand_made_sequence` |
| `src/xlights_mcp/xlights/profile.py` | create | `profile_sequence(xsq_path, show)` |
| `src/xlights_mcp/xlights/palettes.py` | modify | `COLOR_NAMES`, `parse_palette_hint`, `palette_colors` |
| `src/xlights_mcp/sequencer/engine.py` | rewrite parts | section roles, `build_baseline_plan`, new `_generate_auto`, dead code removed |
| `src/xlights_mcp/sequencer/plan_writer.py` | modify | optional `show` parameter (no second parse) |
| `src/xlights_mcp/prompts/__init__.py` | create | `render_sequence_song` |
| `src/xlights_mcp/prompts/sequence_song.md` | create | playbook template |
| `src/xlights_mcp/server.py` | modify | `_show_file` helper, `list_sequences` fields, `profile_sequence` tool, `sequence_song` prompt, `create_sequence` docstring |
| `README.md` | modify | tool rows, prompt section |
| `tests/fixtures/sequences/Human Style.xsq` | create | small hand-made-style sequence with known numbers |
| tests | create/modify | `test_sequence_files.py`, `test_profile.py`, `test_profile_tool.py`, `test_palette_hint.py`, `test_baseline.py`, `test_engine_auto.py`, `test_sequence_song_prompt.py`; `test_engine_groups.py` and `test_engine_write.py` updated |

## Deviations from the spec (approved design) and why

1. **The `sequence_song` prompt does two things on the server:**
   - it picks the default reference (the most recently modified hand-made `.xsq` in the active show);
   - it embeds the show's `.claude/CLAUDE.md` in the message.

   The spec had the model do both itself. Many MCP clients (Claude Desktop, for one) can't read files, and picking the file deterministically is more reliable. `list_sequences` still gains `generated` (and `modified`), so the model can pick a different reference.
2. **Baseline accents avoid the feature groups lit at that moment.** Accents cycle through the accent props that aren't inside a lit feature group. Otherwise every accent would trigger the writer's parent/child warning. When that leaves no props, the full list is used.
3. **`SECTION_TYPE_CONFIG` stays in `engine.py`, as the spec requires, but becomes the baseline's section-role table** (label → `"wash"`, `"features"` or `"accents"`). The old dict held creative settings that the rewrite no longer uses.
4. **Feature effects use `MOTION_EFFECTS` in high-energy sections** (energy ≥ 0.65) and `BED_EFFECTS` otherwise. The spec said "chosen from the existing effect tables by the group's majority model category". `Warp` is removed from the tables, because on layer 0 with nothing beneath it Warp shows nothing.
5. **`profile_sequence` output adds three things:** `timing_tracks` (the reference's timing track names), `"unknown"` in the group/model split (elements that aren't in the active show), and an `other_elements` summary once the per-element rows hit the cap.

Task 8 records these in the spec.

## Domain notes

- **`.xsq` layout:**
  - `<head><sequenceDuration>` is in seconds, e.g. `10.000`.
  - `<ElementEffects><Element type="model"|"timing" name=…>` holds `<EffectLayer>`s, each holding `<Effect name startTime endTime …>`.
  - A layer's number is its position among the element's `<EffectLayer>`s.
  - Timing elements hold `<Effect label=…>` marks.
  - `Off` is a real effect that means dark, so it doesn't count as lit.
- **Generated sequences** contain `<comment>Generated by xLights MCP Server</comment>` in the head. `xsq_writer.GENERATOR_COMMENT` and `xsq_writer.is_generated_sequence(head: bytes)` already exist. The mark sits within the first 4 KB.
- **`build_show_layout(show)`** (in `xlights/layout.py`) returns `{"groups": [row…], …}`, sorted wash → feature → skip, then by name. Each row has:
  - `name` and `tier` (`"wash"`/`"feature"`/`"skip"`)
  - `prop_count`
  - `y_range`: `[lo, hi]` or `None`
  - `accent_props`: the group's leaf models when it's a feature group with at most 8 props, else `[]`
  - `child_groups`, `parent_groups`, `reason`
- **`contained_elements(show)`** (in `xlights/layout.py`): group name → frozenset of its nested groups (transitive) and the real models they reach.
- **Fixture show** (`tests/fixtures/show_groups/xlights_rgbeffects.xml`), with WorldPosY in brackets:
  - Models: Roof Left/Right [150], Under Left/Right [120], Door L/R [20], Pipe 1–14 [5], Lantern1 [90], Lantern2 [100], Lantern3 [110], Arch 1–2 [10], Tree 6ft [40], plus 2 placeholders.
  - `DisplayAs` values: Single Line; Custom for the lanterns; Arches; Tree 360.
  - Tiers:
    - wash: All (23 props), House (6), Everything Flat (25);
    - feature: Door [20–20], Lanterns [90–110], Legacy Arches [10–10], Pipes [5–5], Roof Edges [120–150];
    - everything else is skip.
  - Layout row order for the feature groups: Door, Lanterns, Legacy Arches, Pipes, Roof Edges.
  - Accent props, in that order: Door L, Door R, Lantern1, Lantern2, Lantern3, Arch 1, Arch 2, Roof Left, Roof Right, Under Left, Under Right.
  - Nesting: House ⊃ {Roof Edges ⊃ Under Roof, Door}.
- **`write_plan(plan, analysis, mp3_path, show_path, name=None, timing_tracks=(), extra_tracks=(), overwrite=False, validate_only=False)`** (in `sequencer/plan_writer.py`) returns a report with these keys: `path`, `written`, `elements`, `effects`, `max_layer`, `timing_tracks`, `adjusted`, `errors`, `warnings`.

---

### Task 1: Sequence-file helpers, `list_sequences.generated`, `_show_file`

**Files:**
- Modify: `src/xlights_mcp/xlights/xsq_reader.py`, `src/xlights_mcp/server.py`
- Test: `tests/test_sequence_files.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""Telling generated sequences from hand-made ones, and list_sequences' view of it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from show_fixtures import call_tool

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig
from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.xsq_reader import is_generated_file, latest_hand_made_sequence
from xlights_mcp.xlights.xsq_writer import SequenceSpec, write_xsq

HAND_MADE = "<xsequence><head><comment></comment></head><ElementEffects/></xsequence>"


def _generated(path: Path) -> Path:
    write_xsq(SequenceSpec(duration_ms=1000), ShowConfig(show_path=str(path.parent), show_name="t"), path)
    return path


def _hand_made(path: Path, mtime: float | None = None) -> Path:
    path.write_text(HAND_MADE, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_is_generated_file(tmp_path):
    assert is_generated_file(_generated(tmp_path / "gen.xsq"))
    assert not is_generated_file(_hand_made(tmp_path / "hand.xsq"))


def test_latest_hand_made_sequence_skips_generated_files(tmp_path):
    _hand_made(tmp_path / "Old.xsq", mtime=1_000_000)
    newest = _hand_made(tmp_path / "New.xsq", mtime=2_000_000)
    gen = _generated(tmp_path / "Gen.xsq")
    os.utime(gen, (3_000_000, 3_000_000))

    assert latest_hand_made_sequence(tmp_path) == newest


def test_latest_hand_made_sequence_is_none_without_one(tmp_path):
    _generated(tmp_path / "Gen.xsq")

    assert latest_hand_made_sequence(tmp_path) is None


@pytest.fixture
def active_show(show_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        server_module, "_config", ServerConfig(show_folders={"fixture": str(show_copy)}, active_show="fixture")
    )
    return show_copy


async def test_list_sequences_flags_generated_sequences(active_show):
    _generated(active_show / "Gen.xsq")
    _hand_made(active_show / "Hand.xsq")

    payload = await call_tool("list_sequences", {})

    flags = {s["name"]: s["generated"] for s in payload["sequences"]}
    assert flags == {"Gen": True, "Hand": False}
    assert all(s["modified"] for s in payload["sequences"])


async def test_inspect_sequence_accepts_a_name_with_or_without_the_extension(active_show):
    _hand_made(active_show / "Hand.xsq")

    by_name = await call_tool("inspect_sequence", {"sequence_name": "Hand"})
    by_file = await call_tool("inspect_sequence", {"sequence_name": "Hand.xsq"})

    assert by_name["file_name"] == by_file["file_name"] == "Hand.xsq"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_sequence_files.py -q`
Expected: ImportError (`is_generated_file`).

- [ ] **Step 3: Implement**

In `xsq_reader.py`, add `from xlights_mcp.xlights.xsq_writer import is_generated_sequence`. First check that this doesn't create an import cycle: `xsq_writer` must not import `xsq_reader`. Then add:

```python
_HEAD_BYTES = 4096


def is_generated_file(xsq_path: Path) -> bool:
    """True when the sequence was written by this server's generator."""
    with open(xsq_path, "rb") as f:
        return is_generated_sequence(f.read(_HEAD_BYTES))


def latest_hand_made_sequence(show_path: Path) -> Path | None:
    """The most recently modified .xsq in the folder that this server didn't generate."""
    hand_made = [p for p in show_path.glob("*.xsq") if not is_generated_file(p)]
    return max(hand_made, key=lambda p: p.stat().st_mtime, default=None)
```

If `effects._effect_names_in` still reads its own 4 KB head with a local constant, leave it alone; it needs the head bytes for the full-read decision.

In `server.py`, add this helper next to `_active_show`:

```python
def _show_file(show_path: Path, value: str, suffix: str = "") -> Path:
    """`value` as a path: relative ones resolve against the show folder; `suffix` is added when missing."""
    path = Path(value).expanduser()
    if suffix and path.suffix.lower() != suffix:
        path = path.with_name(path.name + suffix)
    return path if path.is_absolute() else show_path / path
```

Use it:
- **`inspect_sequence`:** replace `xsq_path = show_path / f"{sequence_name}.xsq"` with `xsq_path = _show_file(show_path, sequence_name, ".xsq")`. Also switch its "No active show configured" guard to the shared `_active_show(config)` helper, as the other tools use it.
- **`write_sequence`:** replace the `plan_path` block's manual `plan_file = Path(plan_path).expanduser(); if not plan_file.is_absolute(): …` with `plan_file = _show_file(show_path, plan_path)`.
- **`list_sequences`:** each entry becomes the following. Add `from datetime import datetime` at the top of server.py and import `is_generated_file` inside the function, the way other tools import lazily.

```python
{"name": xsq.stem, "path": str(xsq), "generated": is_generated_file(xsq),
 "modified": datetime.fromtimestamp(xsq.stat().st_mtime).isoformat(timespec="seconds")}
```

Update `list_sequences`' docstring: `generated` is true for sequences written by `create_sequence`/`write_sequence`, false for hand-made ones.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_sequence_files.py tests/test_write_sequence_tool.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/xlights/xsq_reader.py src/xlights_mcp/server.py tests/test_sequence_files.py
git commit -m "list_sequences flags generated sequences; shared show-file path helper"
```

---

### Task 2: Style profile module

**Files:**
- Create: `src/xlights_mcp/xlights/profile.py`
- Create: `tests/fixtures/sequences/Human Style.xsq`
- Test: `tests/test_profile.py` (create)

- [ ] **Step 1: Create the fixture sequence**

Put this in `tests/fixtures/sequences/Human Style.xsq`, exactly as written:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xsequence BaseChannel="0" ChanCtrlBasic="0" ChanCtrlColor="0" FixedPointTiming="1" ModelBlending="true">
  <head>
    <version>2024.10</version>
    <author>Test</author>
    <song>Human Style</song>
    <comment></comment>
    <sequenceTiming>25 ms</sequenceTiming>
    <sequenceType>Media</sequenceType>
    <mediaFile>Human Style.mp3</mediaFile>
    <sequenceDuration>10.000</sequenceDuration>
  </head>
  <ColorPalettes>
    <ColorPalette>C_BUTTON_Palette1=#FFFFFF,C_CHECKBOX_Palette1=1</ColorPalette>
  </ColorPalettes>
  <EffectDB>
    <Effect></Effect>
  </EffectDB>
  <DisplayElements>
    <Element collapsed="0" type="timing" name="Beats" visible="1" views="" active="1"/>
    <Element collapsed="0" type="model" name="House" visible="1"/>
    <Element collapsed="0" type="model" name="Roof Edges" visible="1"/>
    <Element collapsed="0" type="model" name="Lanterns" visible="1"/>
    <Element collapsed="0" type="model" name="Lantern1" visible="1"/>
    <Element collapsed="0" type="model" name="Door" visible="1"/>
    <Element collapsed="0" type="model" name="Tree 6ft" visible="1"/>
  </DisplayElements>
  <ElementEffects>
    <Element type="timing" name="Beats">
      <EffectLayer>
        <Effect label="1" startTime="0" endTime="500"/>
        <Effect label="2" startTime="500" endTime="1000"/>
      </EffectLayer>
    </Element>
    <Element type="model" name="House">
      <EffectLayer>
        <Effect ref="0" name="On" id="1" startTime="0" endTime="4000" palette="0"/>
        <Effect ref="0" name="Color Wash" id="2" startTime="6500" endTime="10000" palette="0"/>
      </EffectLayer>
    </Element>
    <Element type="model" name="Roof Edges">
      <EffectLayer>
        <Effect ref="0" name="SingleStrand" id="3" startTime="2000" endTime="6000" palette="0"/>
      </EffectLayer>
    </Element>
    <Element type="model" name="Lanterns">
      <EffectLayer>
        <Effect ref="0" name="On" id="4" startTime="1000" endTime="1500" palette="0"/>
        <Effect ref="0" name="Twinkle" id="5" startTime="3000" endTime="5000" palette="0"/>
      </EffectLayer>
    </Element>
    <Element type="model" name="Lantern1">
      <EffectLayer>
        <Effect ref="0" name="Off" id="6" startTime="0" endTime="8000" palette="0"/>
      </EffectLayer>
      <EffectLayer>
        <Effect ref="0" name="On" id="7" startTime="8000" endTime="9000" palette="0"/>
      </EffectLayer>
    </Element>
    <Element type="model" name="Door">
      <EffectLayer>
        <Effect ref="0" name="On" id="8" startTime="0" endTime="2000" palette="0"/>
        <Effect ref="0" name="On" id="9" startTime="1500" endTime="2500" palette="0"/>
      </EffectLayer>
    </Element>
    <Element type="model" name="Tree 6ft">
      <EffectLayer/>
    </Element>
  </ElementEffects>
</xsequence>
```

The expected numbers are derived by hand. Keep this derivation with the tests so reviewers can check it.

Lit spans (Off doesn't count):
- House: [0,4000) and [6500,10000)
- Roof Edges: [2000,6000)
- Lanterns: [1000,1500) and [3000,5000)
- Lantern1: [8000,9000)
- Door: [0,2500), merged from two overlapping effects

Elements lit at once, at t = 0, 50, …, 9950 (200 samples):

| Time (ms) | Lit | Samples |
|---|---|---|
| 0–1000 | 2 | |
| 1000–1500 | 3 | |
| 1500–2000 | 2 | |
| 2000–2500 | 3 | |
| 2500–3000 | 2 | |
| 3000–4000 | 3 | |
| 4000–5000 | 2 | |
| 5000–6000 | 1 | |
| 6000–6500 | 0 | 10 |
| 6500–8000 | 1 | |
| 8000–9000 | 2 | |
| 9000–10000 | 1 | |

Totals: 10 samples with 0 lit, 70 with 1, 80 with 2, 40 with 3.
- Median = 2 (sorted samples at index 99 and 100 are both 2).
- p90 = 3 (numpy linear percentile: position 179.1, and index 179 and 180 are both 3).
- Max = 3.
- Dark share = 10/200 = 0.05.

Parent share:
- House contains Roof Edges and Door, both lit. Their union is [0,6000). The overlap with House's spans is [0,4000) = 4000 ms, out of House's 7500 ms lit, giving 0.53.
- Lanterns contains Lantern1 [8000,9000), which doesn't overlap Lanterns, giving 0.0.
- Roof Edges and Door contain nothing lit, so they are omitted.

Elements with effects:
- Groups: Door, House, Lanterns, Roof Edges (4).
- Models: Lantern1 (1).
- Tree 6ft has no effects, so it's omitted.
- 9 effects in total.

Overlaps within a layer: 1 (Door, layer 0).

Rows, sorted by effect count descending, then name:

| Element | Effects | Layers | Median length (ms) | Lit share | Top effects |
|---|---|---|---|---|---|
| Door | 2 | [0] | 1500 | 0.25 | ["On"] |
| House | 2 | [0] | 3750 | 0.75 | ["On", "Color Wash"] |
| Lantern1 | 2 | [0, 1] | 4500 | 0.1 | ["Off", "On"] |
| Lanterns | 2 | [0] | 1250 | 0.25 | ["On", "Twinkle"] |
| Roof Edges | 1 | [0] | 4000 | 0.4 | ["SingleStrand"] |

- [ ] **Step 2: Write the failing tests** (`tests/test_profile.py`)

```python
"""profile_sequence on a small hand-made-style sequence with hand-derived numbers."""

from __future__ import annotations

from pathlib import Path

from show_fixtures import SHOW_GROUPS

from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.profile import MAX_ELEMENT_ROWS, profile_sequence
from xlights_mcp.xlights.show import load_show_config
from xlights_mcp.xlights.xsq_writer import EffectPlacement, SequenceSpec, write_xsq

HUMAN_STYLE = Path(__file__).parent / "fixtures" / "sequences" / "Human Style.xsq"
SHOW = load_show_config(SHOW_GROUPS)


def test_summary_counts():
    profile = profile_sequence(HUMAN_STYLE, SHOW)

    assert profile["duration_ms"] == 10000
    assert profile["elements_with_effects"] == {"groups": 4, "models": 1, "unknown": 0}
    assert profile["total_effects"] == 9
    assert profile["timing_tracks"] == ["Beats"]
    assert profile["overlaps_within_layer"] == 1


def test_concurrency_and_dark_share():
    profile = profile_sequence(HUMAN_STYLE, SHOW)

    assert profile["lit_at_once"] == {"median": 2, "p90": 3, "max": 3}
    assert profile["dark_share"] == 0.05


def test_parent_lit_with_contained_elements():
    assert profile_sequence(HUMAN_STYLE, SHOW)["parent_lit_with_contained"] == {"House": 0.53, "Lanterns": 0.0}


def test_element_rows():
    rows = {r["element"]: r for r in profile_sequence(HUMAN_STYLE, SHOW)["elements"]}

    assert list(rows) == ["Door", "House", "Lantern1", "Lanterns", "Roof Edges"]
    assert rows["House"] == {
        "element": "House", "kind": "group", "layers": [0], "effects": 2,
        "median_ms": 3750, "lit_share": 0.75, "top_effects": ["On", "Color Wash"],
    }
    assert rows["Lantern1"]["kind"] == "model"
    assert rows["Lantern1"]["layers"] == [0, 1]
    assert rows["Lantern1"]["lit_share"] == 0.1
    assert rows["Door"]["lit_share"] == 0.25


def test_rows_are_capped_and_the_rest_summarised(tmp_path):
    effects = [
        EffectPlacement(model_name=f"M{i:02d}", effect_name="On", start_time_ms=0, end_time_ms=1000)
        for i in range(MAX_ELEMENT_ROWS + 5)
    ]
    path = tmp_path / "many.xsq"
    write_xsq(SequenceSpec(duration_ms=2000, effects=effects), ShowConfig(show_path=".", show_name="t"), path)

    profile = profile_sequence(path, SHOW)

    assert len(profile["elements"]) == MAX_ELEMENT_ROWS
    assert profile["other_elements"] == {"count": 5, "effects": 5}
    assert profile["elements_with_effects"]["unknown"] == MAX_ELEMENT_ROWS + 5


def test_no_summary_when_under_the_cap():
    assert profile_sequence(HUMAN_STYLE, SHOW)["other_elements"] is None


def test_duration_falls_back_to_the_last_effect_end(tmp_path):
    path = tmp_path / "nohead.xsq"
    path.write_text(
        '<xsequence><ElementEffects><Element type="model" name="Door"><EffectLayer>'
        '<Effect name="On" startTime="0" endTime="2000"/></EffectLayer></Element></ElementEffects></xsequence>',
        encoding="utf-8",
    )

    assert profile_sequence(path, SHOW)["duration_ms"] == 2000
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_profile.py -q`
Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement `src/xlights_mcp/xlights/profile.py`**

```python
"""Style profile of an .xsq: how many elements are lit together, layering, parents under children."""

from __future__ import annotations

import statistics
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from xlights_mcp.xlights.layout import contained_elements
from xlights_mcp.xlights.models import ShowConfig

SAMPLE_MS = 50
MAX_ELEMENT_ROWS = 20
TOP_EFFECTS = 3

Span = tuple[int, int]


@dataclass
class _Element:
    name: str
    layers: list[list[tuple[str, int, int]]]


def _read(xsq_path: Path) -> tuple[int, list[_Element], list[str]]:
    root = ET.parse(xsq_path).getroot()
    elements: list[_Element] = []
    timing: list[str] = []
    for el in root.iterfind("ElementEffects/Element"):
        name = el.get("name", "")
        if el.get("type") == "timing":
            timing.append(name)
            continue
        layers = [
            [(e.get("name", ""), int(e.get("startTime", "0")), int(e.get("endTime", "0"))) for e in layer.iterfind("Effect")]
            for layer in el.iterfind("EffectLayer")
        ]
        if any(layers):
            elements.append(_Element(name, layers))
    try:
        duration_ms = round(float(root.findtext("head/sequenceDuration", "0")) * 1000)
    except ValueError:
        duration_ms = 0
    if duration_ms <= 0:
        duration_ms = max((end for e in elements for layer in e.layers for _, _, end in layer), default=0)
    return duration_ms, elements, timing


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _length(spans: list[Span]) -> int:
    return sum(end - start for start, end in spans)


def _overlap_length(a: list[Span], b: list[Span]) -> int:
    total = i = j = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        total += max(0, hi - lo)
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def _lit_at_once(lit: dict[str, list[Span]], duration_ms: int) -> np.ndarray:
    samples = max(1, -(-duration_ms // SAMPLE_MS))
    steps = np.zeros(samples + 1, dtype=int)
    for spans in lit.values():
        for start, end in spans:
            first, stop = -(-start // SAMPLE_MS), -(-min(end, duration_ms) // SAMPLE_MS)
            if stop > first:
                steps[first] += 1
                steps[stop] -= 1
    return np.cumsum(steps)[:samples]


def _overlaps(elements: list[_Element]) -> int:
    count = 0
    for element in elements:
        for layer in element.layers:
            latest_end = None
            for _, start, end in sorted(layer, key=lambda e: e[1]):
                if latest_end is not None and start < latest_end:
                    count += 1
                latest_end = end if latest_end is None else max(latest_end, end)
    return count


def profile_sequence(xsq_path: Path, show: ShowConfig) -> dict:
    """Concurrency, darkness, layering and parent/child overlap of a sequence, per the active show."""
    duration_ms, elements, timing_tracks = _read(xsq_path)
    groups = {g.name for g in show.model_groups}
    models = {m.name for m in show.models}
    lit = {
        e.name: _merge([(s, t) for layer in e.layers for name, s, t in layer if name != "Off" and t > s])
        for e in elements
    }

    rows = []
    for e in elements:
        effects = [effect for layer in e.layers for effect in layer]
        rows.append({
            "element": e.name,
            "kind": "group" if e.name in groups else "model" if e.name in models else "unknown",
            "layers": [i for i, layer in enumerate(e.layers) if layer],
            "effects": len(effects),
            "median_ms": round(statistics.median(end - start for _, start, end in effects)),
            "lit_share": round(_length(lit[e.name]) / duration_ms, 2) if duration_ms else 0.0,
            "top_effects": [name for name, _ in Counter(name for name, _, _ in effects).most_common(TOP_EFFECTS)],
        })
    rows.sort(key=lambda r: (-r["effects"], r["element"]))

    counts = _lit_at_once(lit, duration_ms)
    kinds = Counter(r["kind"] for r in rows)

    parent_share = {}
    for parent, members in contained_elements(show).items():
        spans = lit.get(parent)
        inside = _merge([span for m in members if m in lit for span in lit[m]])
        if spans and inside:
            parent_share[parent] = round(_overlap_length(spans, inside) / _length(spans), 2)

    extra = rows[MAX_ELEMENT_ROWS:]
    return {
        "file": xsq_path.name,
        "duration_ms": duration_ms,
        "elements_with_effects": {"groups": kinds["group"], "models": kinds["model"], "unknown": kinds["unknown"]},
        "total_effects": sum(r["effects"] for r in rows),
        "timing_tracks": timing_tracks,
        "lit_at_once": {
            "median": float(np.median(counts)),
            "p90": float(np.percentile(counts, 90)),
            "max": int(counts.max()),
        },
        "dark_share": round(float(np.mean(counts == 0)), 2),
        "parent_lit_with_contained": dict(sorted(parent_share.items(), key=lambda kv: (-kv[1], kv[0]))),
        "overlaps_within_layer": _overlaps(elements),
        "elements": rows[:MAX_ELEMENT_ROWS],
        "other_elements": {"count": len(extra), "effects": sum(r["effects"] for r in extra)} if extra else None,
    }
```

Notes:
- `2.0 == 2` in Python, so the tests' integer expectations for the median and p90 hold.
- `statistics.median` over (2000, 1000) gives 1500.0 and `round` makes it 1500. For Lantern1, (8000, 1000) gives 4500.
- `Counter.most_common` keeps insertion order for ties, which gives `["On", "Color Wash"]` for House.

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_profile.py -q`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add src/xlights_mcp/xlights/profile.py "tests/fixtures/sequences/Human Style.xsq" tests/test_profile.py
git commit -m "profile_sequence: concurrency, dark share, parent/child overlap, layering"
```

---

### Task 3: `profile_sequence` MCP tool

**Files:**
- Modify: `src/xlights_mcp/server.py` (after `inspect_sequence`), `README.md` (Show Management table)
- Test: `tests/test_profile_tool.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""profile_sequence through an in-memory MCP session."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from show_fixtures import call_tool

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig

HUMAN_STYLE = Path(__file__).parent / "fixtures" / "sequences" / "Human Style.xsq"


@pytest.fixture
def active_show(show_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copy(HUMAN_STYLE, show_copy)
    monkeypatch.setattr(
        server_module, "_config", ServerConfig(show_folders={"fixture": str(show_copy)}, active_show="fixture")
    )
    return show_copy


@pytest.mark.parametrize("xsq_path", ["Human Style", "Human Style.xsq"])
async def test_profiles_a_sequence_in_the_show_folder(active_show, xsq_path):
    profile = await call_tool("profile_sequence", {"xsq_path": xsq_path})

    assert profile["file"] == "Human Style.xsq"
    assert profile["lit_at_once"]["median"] == 2


async def test_accepts_an_absolute_path(active_show):
    profile = await call_tool("profile_sequence", {"xsq_path": str(HUMAN_STYLE)})

    assert profile["total_effects"] == 9


async def test_a_missing_sequence_is_an_error(active_show):
    assert "not found" in (await call_tool("profile_sequence", {"xsq_path": "Nope"}))["error"]


async def test_an_unparseable_sequence_is_an_error(active_show):
    (active_show / "Broken.xsq").write_text("<xsequence>", encoding="utf-8")

    assert "Broken.xsq" in (await call_tool("profile_sequence", {"xsq_path": "Broken"}))["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_profile_tool.py -q`
Expected: failures (the tool doesn't exist yet).

- [ ] **Step 3: Implement the tool**

```python
@mcp.tool()
def profile_sequence(xsq_path: str) -> dict:
    """Style profile of a sequence, measured against the active show's layout.

    Use a hand-made sequence as the target style for a new one:
    - lit_at_once: elements lit at the same moment (median / p90 / max), sampled every 50 ms
    - dark_share: share of the song with nothing lit ("Off" effects count as dark)
    - parent_lit_with_contained: per group, the share of its lit time when a group or model
      inside it is also lit (how often parents act as a base under their children)
    - overlaps_within_layer: overlapping effects on one element layer (hand-made sequences have 0)
    - elements: per element (the 20 busiest), its layers, effect count, median effect length,
      share of the song lit and top effect names; other_elements summarises the rest

    Args:
        xsq_path: The sequence file; a name or relative path resolves against the active show
            folder, and ".xsq" is added when missing
    """
    from xlights_mcp.xlights.profile import profile_sequence as build_profile
    from xlights_mcp.xlights.show import load_show_config

    config = get_config()
    show_path = _active_show(config)
    if isinstance(show_path, dict):
        return show_path
    path = _show_file(show_path, xsq_path, ".xsq")
    if not path.exists():
        return {"error": f"Sequence not found: {path}"}
    try:
        return build_profile(path, load_show_config(show_path))
    except ET.ParseError as e:
        return {"error": f"Could not parse {path.name}: {e}"}
```

Add `import xml.etree.ElementTree as ET` at the top of server.py if it isn't there. Use the existing import style.

README: add this row after `inspect_sequence`:

```markdown
| `profile_sequence` | Style profile of a sequence against the show layout: elements lit at once, dark share, parents lit with their children, layers and effects per element — use a hand-made sequence as the target style |
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_profile_tool.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/server.py README.md tests/test_profile_tool.py
git commit -m "profile_sequence MCP tool"
```

---

### Task 4: Palette hints

**Files:**
- Modify: `src/xlights_mcp/xlights/palettes.py`
- Test: `tests/test_palette_hint.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
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
    hint = ", ".join(["red", "green", "blue", "white", "yellow", "orange", "gold", "purple", "pink"])

    assert len(parse_palette_hint(hint)[0]) == 8


def test_the_word_and_inside_a_name_is_not_a_separator():
    assert parse_palette_hint("sandy") == ([], ["sandy"])


def test_no_recognised_colour_falls_back_to_the_theme_palette():
    colors, unknown = palette_colors("teal", "halloween")

    assert colors == ["#FF6600", "#800080", "#00FF00"]
    assert unknown == ["teal"]


def test_no_hint_uses_the_theme_palette():
    assert palette_colors(None, "christmas") == (["#FF0000", "#00FF00", "#FFFFFF"], [])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_palette_hint.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement in `palettes.py`**

Add `import re` at the top. After `get_theme_palettes`:

```python
COLOR_NAMES: dict[str, str] = {
    "red": "#FF0000", "green": "#00FF00", "blue": "#0000FF", "white": "#FFFFFF",
    "warm white": "#FFE4B5", "yellow": "#FFFF00", "orange": "#FF6600", "gold": "#FFD700",
    "purple": "#800080", "pink": "#FF69B4", "magenta": "#FF00FF", "cyan": "#00FFFF", "ice": "#A5F2F3",
}
MAX_PALETTE_COLORS = 8
_HEX_COLOR = re.compile(r"#[0-9a-f]{6}")
_HINT_SEPARATORS = re.compile(r",|\band\b")


def parse_palette_hint(hint: str) -> tuple[list[str], list[str]]:
    """Colours named in a hint such as "red, green and warm white" or "#FF6600 and purple", plus unrecognised words."""
    colors: list[str] = []
    unknown: list[str] = []
    for phrase in _HINT_SEPARATORS.split(hint.lower()):
        phrase = " ".join(phrase.split())
        if not phrase:
            continue
        color = phrase.upper() if _HEX_COLOR.fullmatch(phrase) else COLOR_NAMES.get(phrase)
        if color is None:
            unknown.append(phrase)
        elif color not in colors:
            colors.append(color)
    return colors[:MAX_PALETTE_COLORS], unknown


def palette_colors(hint: str | None, theme: str | None) -> tuple[list[str], list[str]]:
    """The hint's colours, or the theme's first palette's active colours when the hint names none."""
    colors, unknown = parse_palette_hint(hint) if hint else ([], [])
    if not colors:
        palette = next(iter(get_theme_palettes(theme).values()))
        colors = [palette.colors[i - 1] for i in palette.active_colors]
    return colors, unknown
```

Check against the code: the Halloween "classic" palette is `#FF6600, #800080, #00FF00, #000000` with active slots [1, 2, 3], giving orange, purple and green. Christmas "classic" is red, green and white. Christmas is also the default for an unknown or absent theme.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_palette_hint.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/xlights/palettes.py tests/test_palette_hint.py
git commit -m "Palette hints: colour names and hex, with a theme fallback"
```

---

### Task 5: `build_baseline_plan`

**Files:**
- Modify: `src/xlights_mcp/sequencer/engine.py`. This task only **adds** the section-role table, the constants and `build_baseline_plan` with its helpers, and removes `Warp` from `MOTION_EFFECTS`. The old `_generate_auto` stays until Task 6. Because `_generate_auto` reads `SECTION_TYPE_CONFIG` as dicts, give the new role table a temporary name, `SECTION_ROLES`, and swap names in Task 6.
- Test: `tests/test_baseline.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""The create_sequence baseline plan on the fixture show."""

from __future__ import annotations

import numpy as np
from show_fixtures import SHOW_GROUPS, make_analysis

from xlights_mcp.audio.sections import SongSection
from xlights_mcp.sequencer.engine import ACCENT_MS, WASH_BRIGHTNESS, build_baseline_plan
from xlights_mcp.sequencer.plan import validate_plan
from xlights_mcp.xlights.effects import XLIGHTS_EFFECT_NAMES
from xlights_mcp.xlights.show import load_show_config

SHOW = load_show_config(SHOW_GROUPS)
COLORS = ["#FF6600", "#800080"]
SECTIONS = [
    ("intro", 0, 8, 0.2), ("verse", 8, 20, 0.5), ("chorus", 20, 32, 0.8),
    ("breakdown", 32, 40, 0.3), ("drop", 40, 52, 0.9), ("outro", 52, 60, 0.2),
]
ANALYSIS = make_analysis(
    60.0,
    np.arange(0, 60, 0.5).tolist(),
    np.arange(0, 60, 2.0).tolist(),
    sections=[SongSection(label=l, start_time=s, end_time=e, energy_level=en) for l, s, e, en in SECTIONS],
)
FEATURES = {"Door", "Lanterns", "Legacy Arches", "Pipes", "Roof Edges"}
ACCENT_PROPS = {
    "Door L", "Door R", "Lantern1", "Lantern2", "Lantern3", "Arch 1", "Arch 2",
    "Roof Left", "Roof Right", "Under Left", "Under Right",
}


def _plan(exclude=frozenset()):
    return build_baseline_plan(ANALYSIS, SHOW, COLORS, exclude)


def _within(plan, start_s, end_s, layer=None):
    return [
        p for p in plan
        if start_s * 1000 <= p["start_ms"] < end_s * 1000 and (layer is None or p["layer"] == layer)
    ]


def test_the_plan_passes_the_writer_checks():
    result = validate_plan(_plan(), SHOW, 60000, XLIGHTS_EFFECT_NAMES)

    assert result.errors == []


def test_elements_are_wash_or_feature_groups_or_accent_props_on_layers_0_and_1():
    plan = _plan()

    assert {p["element"] for p in plan} <= FEATURES | ACCENT_PROPS | {"Everything Flat"}
    assert {p["layer"] for p in plan} == {0, 1}


def test_quiet_sections_get_only_the_largest_wash_group_dimmed():
    plan = _plan()

    for start, end in [(0, 8), (32, 40), (52, 60)]:
        (wash,) = _within(plan, start, end)
        assert (wash["element"], wash["effect"]) == ("Everything Flat", "Color Wash")
        assert (wash["start_ms"], wash["end_ms"]) == (start * 1000, end * 1000)
        assert wash["palette"] == {"colors": COLORS, "brightness": WASH_BRIGHTNESS}


def test_feature_halves_take_turns_by_height():
    plan = _plan()

    lit = [{p["element"] for p in _within(plan, s, e, layer=0)} for s, e in [(8, 20), (20, 32), (40, 52)]]
    assert lit == [{"Pipes", "Legacy Arches", "Door"}, {"Lanterns", "Roof Edges"}, {"Pipes", "Legacy Arches", "Door"}]


def test_accents_hit_each_downbeat_of_accent_sections_on_props_not_already_lit():
    plan = _plan()

    chorus = _within(plan, 20, 32, layer=1)
    assert [p["start_ms"] for p in chorus] == [20000, 22000, 24000, 26000, 28000, 30000]
    assert all(p["effect"] == "On" and p["end_ms"] - p["start_ms"] == ACCENT_MS for p in chorus)
    assert [p["element"] for p in chorus] == ["Door L", "Door R", "Arch 1", "Arch 2", "Door L", "Door R"]
    assert _within(plan, 8, 20, layer=1) == []


def test_every_placement_uses_the_given_colours():
    assert all(p["palette"]["colors"] == COLORS for p in _plan())


def test_groups_holding_excluded_models_are_left_out():
    plan = _plan(exclude=frozenset({"Lantern2"}))

    elements = {p["element"] for p in plan}
    assert not elements & {"Lanterns", "All", "Everything Flat", "Lantern2"}
    assert {p["element"] for p in _within(plan, 0, 8)} == {"House"}


def test_without_a_wash_group_quiet_sections_stay_dark():
    plan = _plan(exclude=frozenset({"Door L", "Lantern2"}))

    assert _within(plan, 0, 8) == []
```

Before you run them, check the expectations against the implementation below:
- **Height order:** features sorted by `y_range` low end, then name: Pipes [5], Legacy Arches [10], Door [20], Lanterns [90], Roof Edges [120].
  - The first half is ceil(5/2) = 3 groups: {Pipes, Legacy Arches, Door}.
  - The second half is {Lanterns, Roof Edges}.
- **Feature sections** are verse, chorus and drop. They take turns 0, 1, 2, so their halves go A, B, A.
- **Chorus accents:** half B (Lanterns, Roof Edges) is lit. The accent pool in layout order is Door L, Door R, Lantern1–3, Arch 1, Arch 2, Roof Left, Roof Right, Under Left, Under Right. Removing the lit leaves (Lantern1–3 and the four roof/under props) leaves [Door L, Door R, Arch 1, Arch 2]. The accent counter starts at 0, so the six chorus downbeats get Door L, Door R, Arch 1, Arch 2, Door L, Door R.
- **Excluding Lantern2** removes Lanterns, All and Everything Flat. House (6 props) is then the largest wash group left.
- **Excluding Door L as well** removes House too, because House contains Door. No wash group is left.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_baseline.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement in `engine.py`**

1. In `MOTION_EFFECTS`, change `"custom": ["Plasma_fast", "Warp_mirror", "Warp_wavy"]` to `"custom": ["Plasma_fast", "Butterfly_gentle"]`. Warp only reshapes the layers below it, and the baseline puts features on layer 0.
2. Add the imports `from collections import Counter`, `from typing import Literal` and `from xlights_mcp.xlights.layout import build_show_layout`. Keep the `show_tiers` import until Task 6 removes its user.
3. Add after `SECTION_TYPE_CONFIG`:

```python
SectionRole = Literal["wash", "features", "accents"]

SECTION_ROLES: dict[str, SectionRole] = {
    "intro": "wash", "outro": "wash", "breakdown": "wash",
    "chorus": "accents", "drop": "accents", "instrumental": "accents",
    "verse": "features", "bridge": "features", "build": "features",
    "transition": "features", "unknown": "features",
}
ACCENT_MS = 100
WASH_BRIGHTNESS = 40
```

4. Add:

```python
def _height_order(row: dict) -> tuple:
    y_range = row["y_range"]
    return (y_range[0], y_range[1], row["name"]) if y_range else (float("inf"), float("inf"), row["name"])


def _group_categories(show: ShowConfig) -> dict[str, str]:
    by_name = {m.name: m for m in show.models}
    categories = {}
    for group in show.model_groups:
        cats = [by_name[n].model_category for n in group.leaf_models if n in by_name]
        categories[group.name] = Counter(cats).most_common(1)[0][0] if cats else "other"
    return categories


def _placement(element: str, layer: int, key: str, start_ms: int, end_ms: int, palette: dict) -> dict:
    return {
        "element": element, "layer": layer, "effect": _effect_name_from_key(key),
        "start_ms": start_ms, "end_ms": end_ms, "settings": _get_settings(key), "palette": palette,
    }


def build_baseline_plan(
    analysis: SongAnalysis, show: ShowConfig, colors: list[str], exclude: frozenset[str] = frozenset()
) -> list[dict]:
    """Plan placements for the baseline sequence.

    Quiet sections (intro, outro, breakdown) get the largest wash group dimmed. Other sections
    light one half of the feature groups (by height), alternating; chorus, drop and instrumental
    sections add a short "On" on each downbeat, cycling through accent props that aren't inside
    the lit feature groups. Groups holding a model in `exclude` are left out, and so are those
    models as accents.
    """
    layout = build_show_layout(show)
    leaves = {g.name: set(g.leaf_models) for g in show.model_groups}
    usable = [row for row in layout["groups"] if not leaves[row["name"]] & exclude]
    wash = max((r for r in usable if r["tier"] == "wash"), key=lambda r: r["prop_count"], default=None)
    features = sorted((r for r in usable if r["tier"] == "feature"), key=_height_order)
    split = -(-len(features) // 2)
    halves = [features[:split], features[split:]]
    accent_pool = list(dict.fromkeys(
        prop for row in layout["groups"] if row["tier"] == "feature"
        for prop in row["accent_props"] if prop not in exclude
    ))
    categories = _group_categories(show)
    palette = {"colors": colors}

    plan: list[dict] = []
    feature_turn = accent_turn = 0
    for index, section in enumerate(analysis.sections):
        start, end = section.start_time_ms, section.end_time_ms
        if end <= start:
            continue
        role = SECTION_ROLES.get(section.label, "features")
        if role == "wash":
            if wash:
                plan.append(_placement(
                    wash["name"], 0, "ColorWash_slow", start, end, {"colors": colors, "brightness": WASH_BRIGHTNESS}
                ))
            continue

        lit = halves[feature_turn % 2] or halves[0]
        feature_turn += 1
        table = MOTION_EFFECTS if section.energy_level >= HIGH_ENERGY_THRESHOLD else BED_EFFECTS
        for turn, row in enumerate(lit, start=index):
            choices = table.get(categories[row["name"]], table["other"])
            plan.append(_placement(row["name"], 0, choices[turn % len(choices)], start, end, palette))

        if role == "accents":
            lit_props = set().union(*(leaves[row["name"]] for row in lit))
            pool = [p for p in accent_pool if p not in lit_props] or accent_pool
            for downbeat in analysis.beats.downbeat_times:
                if pool and section.start_time <= downbeat < section.end_time:
                    at = round(downbeat * 1000)
                    plan.append(_placement(pool[accent_turn % len(pool)], 1, "On_solid", at, at + ACCENT_MS, palette))
                    accent_turn += 1
    return plan
```

Notes:
- `_placement` takes a variant key. `_effect_name_from_key("On_solid")` is `"On"` and `_get_settings("On_solid")` is `{}`. `"ColorWash_slow"` maps to `"Color Wash"` with its fade settings.
- `set().union(*…)` with an empty `lit` gives `set()`.
- If `features` is empty, `halves` is `[[], []]`, so `lit` is `[]` and there are no feature placements. Accents still come from the (possibly empty) pool.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_baseline.py tests/test_engine_write.py tests/test_engine_groups.py tests/test_engine_labels.py -q`
Expected: all pass. The old engine is still intact.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/sequencer/engine.py tests/test_baseline.py
git commit -m "build_baseline_plan: features take turns, accents on downbeats, wash in quiet sections"
```

---

### Task 6: `create_sequence` auto mode through `write_plan`

**Files:**
- Modify: `src/xlights_mcp/sequencer/engine.py`, `src/xlights_mcp/sequencer/plan_writer.py`, `src/xlights_mcp/server.py` (`create_sequence` docstring), `README.md` (`create_sequence` row)
- Modify tests: `tests/test_engine_groups.py`, `tests/test_engine_write.py`, `tests/test_engine_labels.py`
- Test: `tests/test_engine_auto.py` (create)

- [ ] **Step 1: Write the failing tests** (`tests/test_engine_auto.py`)

```python
"""create_sequence auto mode: the baseline plan written through write_plan."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from show_fixtures import make_analysis

from xlights_mcp.audio.cache import save_cached
from xlights_mcp.audio.lyrics import LyricTrack, LyricWord, PhonemeEvent
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.config import AudioConfig
from xlights_mcp.sequencer import engine
from xlights_mcp.sequencer.engine import generate_sequence


@pytest.fixture
def audio(tmp_path: Path, click_track: Path) -> AudioConfig:
    config = AudioConfig(cache_dir=tmp_path / "cache")
    analysis = make_analysis(
        20.0,
        np.arange(0, 20, 0.5).tolist(),
        np.arange(0, 20, 2.0).tolist(),
        path=click_track,
        sections=[
            SongSection(label="intro", start_time=0.0, end_time=4.0, energy_level=0.2),
            SongSection(label="chorus", start_time=4.0, end_time=20.0, energy_level=0.8),
        ],
    )
    save_cached(analysis, click_track, config.cache_dir)
    return config


def _generate(click_track, show, audio, **kw) -> dict:
    return generate_sequence(mp3_path=click_track, show_path=show, mode="auto", audio_config=audio, **kw)


def _elements(path: str) -> dict[str, list[ET.Element]]:
    root = ET.parse(path).getroot()
    return {
        el.get("name"): [e for layer in el.iterfind("EffectLayer") for e in layer.iterfind("Effect")]
        for el in root.iterfind("ElementEffects/Element")
    }


def test_writes_the_baseline_with_beats_and_bars(click_track, show_copy, audio):
    result = _generate(click_track, show_copy, audio, palette_hint="orange and teal")

    assert result["success"] is True
    assert Path(result["output_path"]) == show_copy / f"{click_track.stem}.xsq"
    assert result["timing_tracks"] == ["Beats", "Bars"]
    assert result["palette"] == ["#FF6600"]
    assert result["palette_unrecognised"] == ["teal"]
    assert result["total_effects"] > 0
    elements = _elements(result["output_path"])
    assert elements["Everything Flat"][0].get("name") == "Color Wash"


def test_never_overwrites_an_existing_sequence(click_track, show_copy, audio):
    (show_copy / f"{click_track.stem}.xsq").write_text("mine", encoding="utf-8")

    result = _generate(click_track, show_copy, audio)

    assert Path(result["output_path"]).name == f"{click_track.stem} (generated 1).xsq"
    assert (show_copy / f"{click_track.stem}.xsq").read_text(encoding="utf-8") == "mine"


def test_a_show_with_only_placeholders_is_an_error(tmp_path, click_track, audio):
    show = tmp_path / "placeholders"
    show.mkdir()
    (show / "xlights_rgbeffects.xml").write_text(
        '<xrgb><models><model name="Spare - Dont Map" DisplayAs="Single Line"/></models></xrgb>', encoding="utf-8"
    )

    assert "error" in _generate(click_track, show, audio)


@pytest.fixture
def singing_show(show_copy: Path) -> Path:
    xml = show_copy / "xlights_rgbeffects.xml"
    text = xml.read_text(encoding="utf-8").replace(
        '<model name="Lantern2" DisplayAs="Custom" WorldPosY="100.0"/>',
        '<model name="Lantern2" DisplayAs="Custom" WorldPosY="100.0"><faceInfo Name="Singing Face"/></model>',
    )
    xml.write_text(text, encoding="utf-8")
    return show_copy


def _lyrics() -> LyricTrack:
    return LyricTrack(
        words=[LyricWord(word="boo", start_time=1.0, end_time=1.5)],
        phonemes=[PhonemeEvent(phoneme="U", start_time_ms=1000, end_time_ms=1500)],
        track_name="Vocals",
        available=True,
    )


def test_singing_models_without_lyrics_get_no_effects_and_a_warning(click_track, singing_show, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [])

    result = _generate(click_track, singing_show, audio)

    assert any("Lyrics unavailable" in w for w in result["warnings"])
    assert "Lantern2" not in _elements(result["output_path"]) or not _elements(result["output_path"])["Lantern2"]


def test_singing_models_need_assignments_before_anything_is_written(click_track, singing_show, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [_lyrics()])

    result = _generate(click_track, singing_show, audio)

    assert result["needs_vocal_assignment"] is True
    assert list(singing_show.glob("*.xsq")) == []


def test_faces_are_sequenced_and_groups_holding_them_left_out(click_track, singing_show, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [_lyrics()])

    result = _generate(click_track, singing_show, audio, vocal_assignments={"all": "Vocals"})

    assert result["has_lyrics"] is True and result["singing_models"] == ["Lantern2"]
    elements = _elements(result["output_path"])
    assert any(e.get("name") == "Faces" for e in elements["Lantern2"])
    assert not elements.get("Lanterns") and not elements.get("Everything Flat")
    assert "Vocals" in result["timing_tracks"]
```

The `"Lantern2" not in … or not …` assertion is deliberate. `write_xsq` lists every show model under ElementEffects, including ones without effects, so Lantern2 may appear with an empty layer.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_engine_auto.py -q`
Expected: failures, because the old engine returns different keys.

- [ ] **Step 3: Implement**

**`plan_writer.py`:** add `show: ShowConfig | None = None` as the last keyword parameter of `write_plan`. Use `show = show or load_show_config(show_path)` instead of loading it unconditionally, and import `ShowConfig` from `xlights_mcp.xlights.models`.

**`engine.py`:**

1. **Delete:**
   - `ACCENT_EFFECTS`, `STEM_MOTION_OVERRIDES`, `STEM_ACCENT_OVERRIDES`
   - the old `SECTION_TYPE_CONFIG` dict and its three alias lines
   - `_LEGACY_GROUP_PATTERNS`, `_detect_model_groups`, `_precompute_section_beats`, `_precompute_section_downbeats`
   - the whole old `_generate_auto`
   - the imports that become unused: `random`, `StemAnalysis`, `SongSection` if unused, `show_tiers`, `SequenceSpec`, `TimingTrackLabel` if unused, `write_xsq`, `LightModel`
   - `EFFECT_VARIANTS` entries and `_effect_name_from_key` entries that no remaining code references (Shockwave_hit, Morph_quick, Meteors_explode, Warp_*). Check what's still used with grep before deleting each one.

   Rename `SECTION_ROLES` to `SECTION_TYPE_CONFIG`. Update `build_baseline_plan` and `tests/test_engine_labels.py`; it still imports `SECTION_TYPE_CONFIG` and its assertion still holds.
2. **Keep:** `generate_sequence`, `preview_sequence_plan`, `_generate_guided_preview`, `_get_settings`, `_effect_name_from_key`, `_try_extract_lyrics`, `_try_extract_vocal_tracks`, `EFFECT_VARIANTS`, `BED_EFFECTS`, `MOTION_EFFECTS`, `HIGH_ENERGY_THRESHOLD` and `LOW_ENERGY_THRESHOLD`.
3. **Module docstring:** replace it with a short one: "Sequence generation: the create_sequence baseline plan, singing faces, and the guided preview."
4. **`generate_sequence`:** change `if not show_config.models:` to `if not show_config.real_models:` with the error `"No models with lights found in show configuration"`.
5. **Add the new auto path:**

```python
FACE_BED_KEYS = ("Twinkle_ambient", "ColorWash_cycling", "Butterfly_gentle")
STEM_TIMING_TRACKS = ("Drums", "Bass", "Instruments")


def _free_sequence_name(show_path: Path, stem: str) -> str:
    name, counter = stem, 1
    while (show_path / f"{name}.xsq").exists():
        name = f"{stem} (generated {counter})"
        counter += 1
    return name


def _lyric_timing_track(track) -> TimingTrack:
    words = [
        TimingTrackLabel(label=w.word, start_time_ms=int(w.start_time * 1000), end_time_ms=int(w.end_time * 1000))
        for w in track.words
    ]
    phonemes = [
        TimingTrackLabel(label=p.phoneme, start_time_ms=p.start_time_ms, end_time_ms=p.end_time_ms)
        for p in track.phonemes
    ]
    return TimingTrack(name=track.track_name, labels=[words, words, phonemes])


def _face_placements(analysis: SongAnalysis, model: str, face_definition: str, track_name: str, colors: list[str]) -> list[dict]:
    palette = {"colors": colors}
    plan = []
    for index, section in enumerate(analysis.sections):
        if section.energy_level >= HIGH_ENERGY_THRESHOLD:
            key = "Twinkle_dense"
        elif section.energy_level < LOW_ENERGY_THRESHOLD:
            key = "ColorWash_slow"
        else:
            key = FACE_BED_KEYS[index % len(FACE_BED_KEYS)]
        plan.append(_placement(model, 0, key, section.start_time_ms, section.end_time_ms, palette))
    plan.append({
        "element": model, "layer": 1, "effect": "Faces", "start_ms": 0, "end_ms": analysis.duration_ms,
        "settings": {
            "E_CHECKBOX_Faces_Outline": "1",
            "E_CHOICE_Faces_EyeBlinkDuration": "Normal",
            "E_CHOICE_Faces_EyeBlinkFrequency": "Normal",
            "E_CHOICE_Faces_Eyes": "Auto",
            "E_CHOICE_Faces_FaceDefinition": face_definition,
            "E_CHOICE_Faces_TimingTrack": track_name,
            "T_TEXTCTRL_Fadein": "0.5",
            "T_TEXTCTRL_Fadeout": "0.5",
        },
        "palette": palette,
    })
    return plan


def _generate_auto(
    analysis: SongAnalysis,
    show_config: ShowConfig,
    mp3_path: Path,
    palette_hint: str | None,
    theme: str | None,
    vocal_assignments: dict[str, str] | None = None,
) -> dict:
    """Write the baseline sequence: the baseline plan plus singing faces, through write_plan."""
    show_path = Path(show_config.show_path)
    colors, unrecognised = palette_colors(palette_hint, theme)
    singing = {m.name: m.face_definitions[0] for m in show_config.real_models if m.face_definitions}
    warnings: list[str] = []
    faces: list[dict] = []
    lyric_tracks: list[TimingTrack] = []
    assignments: dict[str, str] = {}

    if singing:
        vocal_tracks = _try_extract_vocal_tracks(mp3_path)
        if not vocal_tracks:
            warnings.append(
                f"Lyrics unavailable, so singing models {sorted(singing)} get no face effects "
                "(install the lyrics extra for Whisper)"
            )
        elif vocal_assignments is None:
            return {
                "needs_vocal_assignment": True,
                "singing_models": [{"model_name": m, "face_definition": f} for m, f in singing.items()],
                "vocal_tracks": [
                    {"track_name": t.track_name, "source": t.source, "word_count": len(t.words)} for t in vocal_tracks
                ],
                "message": (
                    "Singing face models and vocal tracks detected. "
                    "Please assign vocal tracks to models using the vocal_assignments parameter. "
                    "Pass a dict mapping model names to track names, "
                    'or use {"all": "<track_name>"} to assign one track to all singing models.'
                ),
            }
        else:
            by_name = {t.track_name: t for t in vocal_tracks}
            for model, face_definition in singing.items():
                requested = vocal_assignments.get("all", vocal_assignments.get(model))
                track = by_name.get(requested, vocal_tracks[0])
                assignments[model] = track.track_name
                faces.extend(_face_placements(analysis, model, face_definition, track.track_name, colors))
            lyric_tracks = [_lyric_timing_track(t) for t in vocal_tracks]

    plan = build_baseline_plan(analysis, show_config, colors, frozenset(singing) if faces else frozenset()) + faces
    stems = STEM_TIMING_TRACKS if analysis.stem_analysis.available else ()
    report = write_plan(
        plan, analysis, mp3_path, show_path,
        name=_free_sequence_name(show_path, mp3_path.stem),
        timing_tracks=("Beats", "Bars", *stems),
        extra_tracks=lyric_tracks,
        show=show_config,
    )
    if not report["written"]:
        return {"error": "The baseline plan failed validation; this is a bug.", "report": report}

    return {
        "success": True,
        "output_path": report["path"],
        "song": mp3_path.stem,
        "duration": f"{analysis.duration_seconds:.1f}s",
        "tempo": f"{analysis.beats.tempo:.0f} BPM",
        "sections": len(analysis.sections),
        "elements": report["elements"],
        "total_effects": report["effects"],
        "layers_used": report["max_layer"] + 1 if report["effects"] else 0,
        "palette": colors,
        "palette_unrecognised": unrecognised,
        "timing_tracks": report["timing_tracks"],
        "has_lyrics": bool(faces),
        "singing_models": sorted(singing) if faces else [],
        "vocal_assignments": assignments,
        "warnings": warnings + report["warnings"],
        "message": (
            f"Sequence created: {Path(report['path']).name}. This is a simple baseline; for a "
            "hand-made-style sequence use the sequence_song prompt with write_sequence."
        ),
    }
```

   Imports needed: `from xlights_mcp.sequencer.plan_writer import write_plan`, `from xlights_mcp.xlights.palettes import palette_colors` (and `DEFAULT_PALETTE` only if still used), plus `TimingTrack` and `TimingTrackLabel` from `xsq_writer`.

   Singing-model effects with no assignment default to the first track, as before. `vocal_assignments.get("all", …)` covers the `{"all": …}` shorthand.
6. **`tests/test_engine_groups.py`:** delete the `_detect_model_groups` tests (`test_engine_groups_are_the_feature_tier_groups`, `test_engine_groups_honor_tier_overrides`) and the now-unused imports. Keep `test_placeholders_are_not_sequenced` and `test_guided_preview_omits_placeholders`. Add one replacement for the override test:

```python
def test_baseline_honors_tier_overrides(tmp_path):
    show_dir = tmp_path / "show"
    shutil.copytree(SHOW, show_dir)
    (show_dir / "xlights-mcp.json").write_text(json.dumps({"tiers": {"Pipes-Odd": "feature"}}), encoding="utf-8")
    show = load_show_config(show_dir)
    analysis = make_analysis(
        8.0, [], [0.0, 2.0, 4.0, 6.0],
        sections=[SongSection(label="verse", start_time=0.0, end_time=4.0), SongSection(label="verse", start_time=4.0, end_time=8.0)],
    )

    elements = {p["element"] for p in build_baseline_plan(analysis, show, ["#FFFFFF"])}

    assert "Pipes-Odd" in elements
```

   With 6 features (Pipes [5], Pipes-Odd [5], Legacy Arches [10], Door [20], Lanterns [90], Roof Edges [120]), the two verse sections light both halves, so every feature group appears. Import `make_analysis` from `show_fixtures` and `SongSection` from `xlights_mcp.audio.sections`.
7. **`tests/test_engine_write.py`:** keep the test and its assertions. It still passes because every writer effect carries `ref` and `palette`. Add `assert result["success"] is True` at the end.
8. **`server.py` `create_sequence` docstring:** rewrite it to describe the baseline:
   - "auto" writes a simple baseline: quiet sections (intro, outro, breakdown) get the largest wash group dimmed; other sections light half of the feature groups at a time, alternating by height; chorus, drop and instrumental sections add short hits on accent props at each downbeat.
   - It includes Beats and Bars timing tracks, plus Drums, Bass and Instruments when stems are available.
   - It never overwrites; it picks "<song> (generated N)".
   - For a hand-made-style sequence, use the `sequence_song` prompt and `write_sequence`.
   - `palette_hint` takes colour names (red, green, blue, white, warm white, yellow, orange, gold, purple, pink, magenta, cyan, ice) or `#RRGGBB`, separated by commas and/or "and". Unrecognised words are reported and ignored. With no usable hint, the theme's palette is used.
   - Keep the `mode`, `theme`, `vocal_assignments` and `show_name` descriptions.
9. **README:** change the `create_sequence` row to: "Generate a baseline `.xsq` from an `.mp3`: wash in quiet sections, feature groups taking turns, accents on downbeats (use the `sequence_song` prompt for hand-made-style sequences)".

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_engine_auto.py tests/test_engine_groups.py tests/test_engine_write.py tests/test_engine_labels.py tests/test_baseline.py tests/test_plan_writer.py -q`
Expected: all pass. Then run the full suite: `.venv/Scripts/python -m pytest -q`, which should all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/sequencer/engine.py src/xlights_mcp/sequencer/plan_writer.py src/xlights_mcp/server.py README.md tests/test_engine_auto.py tests/test_engine_groups.py tests/test_engine_write.py tests/test_engine_labels.py
git commit -m "create_sequence auto: baseline plan and singing faces written through write_plan"
```

---

### Task 7: `sequence_song` prompt

**Files:**
- Create: `src/xlights_mcp/prompts/__init__.py`, `src/xlights_mcp/prompts/sequence_song.md`
- Modify: `src/xlights_mcp/server.py` (register the prompt near the end, before the FPP tools), `README.md` (new "Prompts" section after the tool tables)
- Test: `tests/test_sequence_song_prompt.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""The sequence_song playbook prompt."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
from xlights_mcp.config import ServerConfig
from xlights_mcp.prompts import render_sequence_song

HUMAN_STYLE = Path(__file__).parent / "fixtures" / "sequences" / "Human Style.xsq"


def test_renders_every_placeholder():
    text = render_sequence_song("C:/music/Song.mp3", None, None)

    assert "C:/music/Song.mp3" in text
    assert "{{" not in text and "}}" not in text


def test_a_reference_is_profiled():
    text = render_sequence_song("Song.mp3", "Human Style.xsq", None)

    assert "profile_sequence" in text and "Human Style.xsq" in text


def test_without_a_reference_it_gives_default_targets():
    text = render_sequence_song("Song.mp3", None, None)

    assert "no hand-made sequence" in text.lower()


def test_show_notes_are_embedded():
    assert "Never light the neighbours' side" in render_sequence_song("Song.mp3", None, "Never light the neighbours' side")


@pytest.fixture
def active_show(show_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        server_module, "_config", ServerConfig(show_folders={"fixture": str(show_copy)}, active_show="fixture")
    )
    return show_copy


async def _get(args: dict) -> str:
    async with create_connected_server_and_client_session(server_module.mcp) as client:
        prompts = await client.list_prompts()
        assert "sequence_song" in {p.name for p in prompts.prompts}
        result = await client.get_prompt("sequence_song", args)
    return result.messages[0].content.text


async def test_prompt_defaults_to_the_latest_hand_made_sequence(active_show):
    shutil.copy(HUMAN_STYLE, active_show)

    text = await _get({"mp3_path": "Song.mp3"})

    assert "Human Style.xsq" in text


async def test_an_explicit_reference_wins(active_show):
    shutil.copy(HUMAN_STYLE, active_show)

    text = await _get({"mp3_path": "Song.mp3", "reference_sequence": "Other.xsq"})

    assert "Other.xsq" in text and "Human Style.xsq" not in text


async def test_show_claude_md_is_embedded(active_show):
    (active_show / ".claude").mkdir()
    (active_show / ".claude" / "CLAUDE.md").write_text("Keep the tombstones white.", encoding="utf-8")

    assert "Keep the tombstones white." in await _get({"mp3_path": "Song.mp3"})
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_sequence_song_prompt.py -q`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

`src/xlights_mcp/prompts/__init__.py`:

```python
"""MCP prompt templates; the text lives in Markdown files next to this module."""

from __future__ import annotations

from pathlib import Path

_SEQUENCE_SONG = Path(__file__).with_name("sequence_song.md")

_WITH_REFERENCE = (
    "Call `profile_sequence` with `xsq_path` = `{reference}`, a hand-made sequence from this show. "
    "Use it as the target style:\n"
    "- `lit_at_once`: how many elements are lit together;\n"
    "- `dark_share`: how often the show goes dark;\n"
    "- `parent_lit_with_contained`: how often a parent group is a base under its children;\n"
    "- per-element layers and effect lengths: whether groups or single props carry the effects."
)
_WITHOUT_REFERENCE = (
    "This show has no hand-made sequence to learn from (check `list_sequences` for one with "
    "`generated: false` if the user names one). Aim for what hand-made sequences typically do:\n"
    "- a median of 2–5 elements lit at once;\n"
    "- under 5% of the song fully dark;\n"
    "- groups carrying most effects, with single props only for accents;\n"
    "- no overlaps within a layer."
)


def render_sequence_song(mp3_path: str, reference: str | None, show_notes: str | None) -> str:
    """The sequence_song playbook for a song, a reference sequence and the show's notes."""
    notes = f"\n### Show notes\n\nThe show folder's `.claude/CLAUDE.md` says:\n\n{show_notes.strip()}\n" if show_notes else ""
    return (
        _SEQUENCE_SONG.read_text(encoding="utf-8")
        .replace("{{mp3_path}}", mp3_path)
        .replace("{{reference_step}}", _WITH_REFERENCE.format(reference=reference) if reference else _WITHOUT_REFERENCE)
        .replace("{{show_notes}}", notes)
    )
```

`src/xlights_mcp/prompts/sequence_song.md` (exact content):

````markdown
# Sequence {{mp3_path}}

You are sequencing a song for this xLights light show. The server gives you facts about the song and the show, and a writer that checks every plan; the creative decisions are yours. Work through these steps in order and don't skip validation.

## 1. Understand the song

Call `analyze_song` with `mp3_path` = `{{mp3_path}}`. Note:
- the tempo;
- the sections, with label, start and end, and energy;
- whether drums are present in each section;
- whether stems are available (`stems` is not null).

For exact beat and downbeat times, use `get_beat_map`. For drum and bass hits worth accenting, use `get_stem_events`.

## 2. Understand the show

Call `get_show_layout`. Every group has a tier:
- **wash**: big groups covering most of the display. Use them as a base under features (dimmed), or for full-show hits.
- **feature**: the groups that carry the choreography. Rotate motion between them.
- **skip**: subsets, duplicates, submodel groups, single props and preview-only groups. Don't sequence these unless the user asks.

`accent_props` lists single props suited to short hits. `y_range` tells you what is high (rooflines) and what is low (ground props).
{{show_notes}}
## 3. Learn the target style

{{reference_step}}

## 4. Plan section by section

For each section, decide what carries it:
- **Wash base:** use a wash group as a base only where the section's energy and the reference call for it, such as quiet intros or big drops.
- **Rotation:** rotate which feature groups carry motion between sections and phrases, and don't light everything at once. Match the reference's concurrency and dark share.
- **Accents:** put short accents (20–200 ms) on accent props at hits, for example kick or snare onsets in a drop, or downbeats in a chorus.
- **Energy:** build energy with effect speed, density and brightness, not by stacking layers. Use at most 3 layers (0–2) per element; most elements need only layer 0.
- **Parents and children:** a group lit at the same time as a group or model inside it reads as one element, and the writer warns about it. Do it on purpose (a dim parent base under a bright child), not by accident.
- **Overlaps:** effects on the same element and layer must not overlap. End one where the next starts.

A placement looks like this:

```json
{"element": "Roof Edges", "layer": 0, "effect": "SingleStrand", "start_ms": 12000, "end_ms": 14000,
 "settings": {"E_NOTEBOOK_SSEFFECT_TYPE": "Chase", "E_CHOICE_Chase_Type1": "Left-Right"},
 "palette": {"colors": ["#7FE7FF", "#00C8FF"], "brightness": 80}}
```

`settings` is optional: xLights uses each effect's defaults for anything you leave out. Some useful settings:
- **SingleStrand chase:** `E_NOTEBOOK_SSEFFECT_TYPE` = `Chase`; `E_CHOICE_Chase_Type1` = `Left-Right`, `Right-Left`, `From Middle` or `Bounce from Left`; `E_SLIDER_Chase_Rotations` sets the number of passes.
- **Color Wash:** `E_TEXTCTRL_ColorWash_Cycles` sets the colour cycles over the effect.
- **Twinkle:** `E_SLIDER_Twinkle_Count` sets the density and `E_SLIDER_Twinkle_Steps` the speed (lower is faster).
- **Shockwave:** `E_SLIDER_Shockwave_Start_Radius` and `E_SLIDER_Shockwave_End_Radius` (0–250).
- **VU Meter synced to a timing track:** `E_CHOICE_VUMeter_Type` = `Timing Event Color` and `E_CHOICE_VUMeter_TimingTrack` = `Beats`.
- **Fades:** `T_TEXTCTRL_Fadein` and `T_TEXTCTRL_Fadeout`, in seconds.

`palette` takes 1–8 `#RRGGBB` colours, a `brightness` of 0–400 (default 100) and `sparkles` of 0–200. Without a palette, the effect is white.

For a long plan, write the placements to a JSON file in the show folder and pass `plan_path` instead of `plan`.

## 5. Validate, then write

1. Call `write_sequence` with `mp3_path` = `{{mp3_path}}`, your plan, and `timing_tracks: ["Beats", "Bars"]`. Add `"Drums"` when stems are available. Set `validate_only: true`.
2. Fix every error it reports and call again until there are none. Read the warnings.
3. Call it once more without `validate_only`. Pass `overwrite: true` only if the user agreed to replace an existing sequence.
4. Report the file path, the effect count, and any warnings you chose to keep.
````

`server.py`, near the end, before the FPP section:

```python
@mcp.prompt()
def sequence_song(mp3_path: str, reference_sequence: str | None = None) -> str:
    """Plan and write a hand-made-style sequence for a song using the show's groups."""
    from xlights_mcp.prompts import render_sequence_song
    from xlights_mcp.xlights.xsq_reader import latest_hand_made_sequence

    show_path = get_config().active_show_path
    reference, notes = reference_sequence, None
    if show_path and show_path.exists():
        if reference is None:
            latest = latest_hand_made_sequence(show_path)
            reference = latest.name if latest else None
        notes_file = show_path / ".claude" / "CLAUDE.md"
        if notes_file.exists():
            notes = notes_file.read_text(encoding="utf-8-sig")
    return render_sequence_song(mp3_path, reference, notes)
```

README: add a "Prompts" section after the tool tables:

```markdown
### Prompts
| Prompt | Description |
|--------|-------------|
| `sequence_song` | Playbook for a hand-made-style sequence: analyse the song, read the show layout, profile a hand-made reference sequence (the most recent one by default), plan section by section, then validate and write with `write_sequence`. Includes the show folder's `.claude/CLAUDE.md` when present |
```

Hatch packages the whole `src/xlights_mcp` directory (`[tool.hatch.build.targets.wheel] packages = ["src/xlights_mcp"]`), so the `.md` file ships with the package. No packaging change is needed.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_sequence_song_prompt.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/prompts/__init__.py src/xlights_mcp/prompts/sequence_song.md src/xlights_mcp/server.py README.md tests/test_sequence_song_prompt.py
git commit -m "sequence_song prompt: the sequencing playbook"
```

---

### Task 8: Spec notes, full verification, manual checks

**Files:**
- Modify: `docs/superpowers/specs/2026-09-28-group-sequencing-design.md` (record the deviations)

- [ ] **Step 1: Record the deviations in the spec**

Add a short "Implementation notes (PR 3)" subsection at the end of the spec, listing deviations 1–5 from this plan in one line each. Commit:

```bash
git add docs/superpowers/specs/2026-09-28-group-sequencing-design.md
git commit -m "Spec: PR 3 implementation notes"
```

- [ ] **Step 2: Full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: every test passes, 1 deselected.

- [ ] **Step 3: Manual checks.** These are read-only against `E:\XLights`, and anything written goes into a scratch copy in the session scratchpad `C:\Users\slick\AppData\Local\Temp\claude\E--\8c935770-b48a-44ae-b6a1-39ac9cf09310\scratchpad`.

1. **Profile the two reference sequences.** Profile `E:\XLights\HalloweenShow\Corpse Bride - Remains of the Day.xsq` against `load_show_config(Path(r"E:\XLights\HalloweenShow"))`, and `E:\XLights\ChristmasShow\Into the Unknown.xsq` against the Christmas show. Compare with the spec's *Problem* table:
   - Remains: 19 groups / 15 models, 0 overlaps, median 5 / p90 13 lit, 2% dark, House ≈51%, All ≈39%.
   - Unknown: 14 / 6, 0, 2 / 6, 4%, All ≈50%, House ≈21%.

   Report the numbers side by side. Small differences are expected where the old measurement counted only child *groups*. Explain any larger gap rather than tuning the code to match.
2. **Baseline on the real show.** Copy the Halloween show's `xlights_rgbeffects.xml` into a scratch folder. Run `generate_sequence(mp3_path=Path(r"E:\XLights\HalloweenShow\Music\GhostsnStuffft.RobSwire.mp3"), show_path=<scratch>, mode="auto", audio_config=load_config().audio, palette_hint="orange and purple")`. The analysis is cached. Expect:
   - `success`, zero writer errors, and `layers_used` ≤ 2;
   - elements only from the wash/feature tiers and the accent props;
   - Beats, Bars, Drums, Bass and Instruments timing tracks.

   Then profile the result and report its concurrency and dark share next to the human numbers.
3. **Prompt against the real show.** Render the prompt with the Halloween show active: `ServerConfig` with the Halloween folder, then call `sequence_song("…GhostsnStuffft.RobSwire.mp3")` directly. Confirm the default reference is a hand-made `.xsq`, and that the show's `.claude/CLAUDE.md` is embedded if the folder has one.

- [ ] **Step 4: Report** the results to the controller. Don't push or open a PR.
