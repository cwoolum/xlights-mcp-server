# Plan Writer (`write_sequence`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `write_sequence` MCP tool: it validates an LLM-authored effect plan against the show and song, then writes it as an `.xsq`. This is PR 2 of `docs/superpowers/specs/2026-09-28-group-sequencing-design.md` (section *Plan writer*).

**Architecture:** Three focused modules feed the existing `write_xsq`:
- `sequencer/plan.py` turns plan dicts into `EffectPlacement`s with errors, warnings and auto-fix counts.
- `sequencer/timing.py` builds the named timing tracks from the analysis.
- `sequencer/plan_writer.py` (`write_plan`) combines them, decides the output path and writes the file. PR 3's baseline `create_sequence` will call it.

`write_xsq` itself gains three things: palettes collected from placements, a default white palette, and layer-position padding. The server tool is a thin async wrapper around `_analyze_in_thread` plus `write_plan`.

**Tech Stack:** Python 3.12, pydantic v2, FastMCP (mcp<2), `xml.etree.ElementTree`, pytest + pytest-asyncio (auto mode).

---

## Ground rules for every task

- Branch: `feat/plan-writer`, which is stacked on `feat/group-sequencing` (PR 1). Don't rebase or merge anything.
- Python is `.venv/Scripts/python` from the repo root `E:\xlights-mcp-server`. Never run `uv run`, `uv sync` or `uv pip install -e`.
- Run tests with `.venv/Scripts/python -m pytest <path> -q`.
- Commit only the files the task names: `git add <paths>` then `git commit -m ...`. Never use `git commit -a`, `git add .`, `git add -A` or `git stash`.
- End each commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Comments: none that restate the code. Keep docstrings short and match the surrounding style.
- Before the final task, the full suite must pass: `.venv/Scripts/python -m pytest -q`. The baseline is 319 passed, 1 deselected.

## File structure

| File | Change | Responsibility |
|---|---|---|
| `src/xlights_mcp/xlights/palettes.py` | modify | `ColorPalette.brightness`, `DEFAULT_PALETTE` |
| `src/xlights_mcp/xlights/xsq_writer.py` | modify | palettes from placements, default palette, empty lower layers, settings kept in insertion order; drop `SequenceSpec.palettes` |
| `src/xlights_mcp/sequencer/engine.py` | modify (1 line) | stop passing `palettes=` |
| `src/xlights_mcp/xlights/effects.py` | modify | `XLIGHTS_EFFECT_NAMES`, `known_effect_names(show_path)`, library reconciled to real names |
| `src/xlights_mcp/xlights/layout.py` | modify | `contained_elements(show)` (transitive group membership) |
| `src/xlights_mcp/sequencer/timing.py` | create | `FRAME_MS`, `to_frame`, `last_frame_ms`, `beat_labels`, `build_timing_tracks` |
| `src/xlights_mcp/sequencer/plan.py` | create | `validate_plan` → `ValidatedPlan` |
| `src/xlights_mcp/sequencer/plan_writer.py` | create | `write_plan` → report dict |
| `src/xlights_mcp/server.py` | modify | `write_sequence` tool |
| `README.md` | modify | tool-table row |
| tests | create | `test_palettes.py`, `test_xsq_writer.py`, `test_engine_write.py`, `test_effect_names.py`, `test_timing_tracks.py`, `test_plan_validation.py`, `test_plan_writer.py`, `test_write_sequence_tool.py`; one test added to `test_layout.py` |

## Domain notes

- **Layers:** an xLights `.xsq` has `<ElementEffects><Element type="model" name=…><EffectLayer>…`. A layer's number is its position among the element's `<EffectLayer>`s. Groups are written as `type="model"` elements too.
- **Effect attributes:** each `<Effect>` has `ref` (an index into `<EffectDB>`, where the settings string lives) and `palette` (an index into `<ColorPalettes>`). Every effect in hand-made sequences has a palette.
- **Palette strings:** `C_BUTTON_Palette1..8=#RRGGBB`, then `C_CHECKBOX_PaletteN=1` for each active slot, then optionally `C_SLIDER_Brightness=N` and `C_SLIDER_SparkleFrequency=N`.
- **Settings strings:** `K=V,K=V`. A value may itself contain `=`; value curves look like `E_VALUECURVE_X=Active=TRUE|Min=1|`. Always split each part on its **first** `=` only.
- **Frames:** sequences use a 25 ms frame (`SequenceSpec.timing_ms`).
- **Timing tracks:** each is an `Element type="timing"` whose layer holds `<Effect label=… startTime=… endTime=…>` marks. Hand-made shows label beats `1,2,3,4` and bars `1,2,3…`.
- **Test show:** the fixture `tests/fixtures/show_groups/xlights_rgbeffects.xml` contains:
  - models: Roof Left/Right, Under Left/Right, Door L/R, Pipe 1–14, Lantern1–3, Arch 1–2 and Tree 6ft, plus 2 placeholders;
  - groups: All ⊃ House ⊃ {Roof Edges ⊃ Under Roof, Door}; Pipes; Pipes-Odd; Pipe Rows (submodels `Pipe 1/Top`); Lanterns; Everything Flat (all 25 real leaves plus a placeholder); Empty; PreviewONLY All; Single; Cycle A ↔ Cycle B (a cycle, B also holds Door L); Legacy Arches.

---

### Task 1: Palette brightness and default palette

**Files:**
- Modify: `src/xlights_mcp/xlights/palettes.py`
- Test: `tests/test_palettes.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""ColorPalette serialisation."""

from __future__ import annotations

from xlights_mcp.xlights.palettes import DEFAULT_PALETTE, ColorPalette


def test_brightness_is_omitted_at_its_default():
    parts = ColorPalette(colors=["#FF0000"], active_colors=[1]).to_xlights_string().split(",")

    assert not any(p.startswith("C_SLIDER_Brightness") for p in parts)


def test_brightness_is_written_when_changed():
    parts = ColorPalette(colors=["#FF0000"], active_colors=[1], brightness=40).to_xlights_string().split(",")

    assert "C_SLIDER_Brightness=40" in parts


def test_default_palette_is_white_in_slot_one_only():
    parts = DEFAULT_PALETTE.to_xlights_string().split(",")

    assert "C_BUTTON_Palette1=#FFFFFF" in parts
    assert [p for p in parts if p.startswith("C_CHECKBOX_")] == ["C_CHECKBOX_Palette1=1"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_palettes.py -q`
Expected: ImportError (`DEFAULT_PALETTE`).

- [ ] **Step 3: Implement**

In `ColorPalette`, add the field after `sparkle_color`:

```python
    brightness: int = 100
```

In `to_xlights_string`, between the active-checkbox loop and the sparkle block:

```python
        if self.brightness != 100:
            parts.append(f"C_SLIDER_Brightness={self.brightness}")
```

After the class:

```python
DEFAULT_PALETTE = ColorPalette(colors=["#FFFFFF"], active_colors=[1])
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_palettes.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/xlights/palettes.py tests/test_palettes.py
git commit -m "Palette brightness and a default white palette"
```

---

### Task 2: `write_xsq` palettes, default palette, layer positions

**Files:**
- Modify: `src/xlights_mcp/xlights/xsq_writer.py`
- Modify: `src/xlights_mcp/sequencer/engine.py` (the `SequenceSpec(...)` call near line 867)
- Test: `tests/test_xsq_writer.py` (create), `tests/test_engine_write.py` (create)

- [ ] **Step 1: Write the engine characterization test and check it passes on the current code**

`tests/test_engine_write.py`:

```python
"""create_sequence's auto mode still writes a well-formed sequence through write_xsq."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.cache import save_cached
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.config import AudioConfig
from xlights_mcp.sequencer.engine import generate_sequence

SHOW = Path(__file__).parent / "fixtures" / "show_groups"


def test_auto_mode_writes_effects_with_refs_and_palettes(tmp_path: Path, click_track: Path):
    show = tmp_path / "show"
    show.mkdir()
    shutil.copy(SHOW / "xlights_rgbeffects.xml", show)
    audio = AudioConfig(cache_dir=tmp_path / "cache")
    save_cached(
        SongAnalysis(
            file_path=str(click_track),
            file_name=click_track.name,
            duration_seconds=20.0,
            beats=BeatMap(
                tempo=120.0,
                beat_times=np.arange(0, 20, 0.5).tolist(),
                downbeat_times=np.arange(0, 20, 2.0).tolist(),
            ),
            sections=[SongSection(label="chorus", start_time=0.0, end_time=20.0, energy_level=0.8)],
        ),
        click_track,
        audio.cache_dir,
    )

    result = generate_sequence(mp3_path=click_track, show_path=show, mode="auto", audio_config=audio)

    root = ET.parse(result["output_path"]).getroot()
    effects = [e for e in root.iter("Effect") if e.get("name")]
    assert effects
    assert all(e.get("ref") is not None and e.get("palette") is not None for e in effects)
```

Run: `.venv/Scripts/python -m pytest tests/test_engine_write.py -q`
Expected: it **fails** on today's code with an `AssertionError` on the ref/palette check, because `write_xsq` drops any placement palette that isn't pre-registered. If it passes instead, carry on: the test still guards the refactor.

- [ ] **Step 2: Write the failing writer tests**

`tests/test_xsq_writer.py`:

```python
"""write_xsq output structure."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.palettes import DEFAULT_PALETTE, ColorPalette
from xlights_mcp.xlights.xsq_writer import EffectPlacement, SequenceSpec, write_xsq

SHOW = ShowConfig(show_path=".", show_name="test")


def _write(tmp_path: Path, *effects: EffectPlacement) -> ET.Element:
    out = tmp_path / "s.xsq"
    write_xsq(SequenceSpec(duration_ms=10000, effects=list(effects)), SHOW, out)
    return ET.parse(out).getroot()


def _on(element: str, **kw) -> EffectPlacement:
    return EffectPlacement(model_name=element, effect_name="On", start_time_ms=0, end_time_ms=500, **kw)


def _placed(root: ET.Element) -> list[ET.Element]:
    return root.findall("ElementEffects/Element/EffectLayer/Effect")


def test_a_layer_two_placement_keeps_its_layer_position(tmp_path):
    root = _write(tmp_path, _on("Roof", layer=2))

    layers = root.findall("ElementEffects/Element[@name='Roof']/EffectLayer")
    assert [len(layer) for layer in layers] == [0, 0, 1]


def test_palettes_are_collected_from_placements_and_deduplicated(tmp_path):
    red = ColorPalette(colors=["#FF0000"], active_colors=[1])
    blue = ColorPalette(colors=["#0000FF"], active_colors=[1], brightness=50)

    root = _write(tmp_path, _on("A", palette=red), _on("B", palette=red), _on("C", palette=blue))

    assert [p.text for p in root.findall("ColorPalettes/ColorPalette")] == [
        red.to_xlights_string(),
        blue.to_xlights_string(),
    ]
    assert {e.get("palette") for e in _placed(root)} == {"0", "1"}


def test_an_effect_without_a_palette_gets_the_default_palette(tmp_path):
    root = _write(tmp_path, _on("A"))

    assert root.find("ColorPalettes/ColorPalette").text == DEFAULT_PALETTE.to_xlights_string()
    assert _placed(root)[0].get("palette") == "0"


def test_settings_keep_their_order_and_every_effect_refs_them(tmp_path):
    root = _write(
        tmp_path,
        _on("A", settings={"Z_LAST": "1", "A_FIRST": "2"}),
        _on("B"),
    )

    db = [e.text or "" for e in root.findall("EffectDB/Effect")]
    by_element = {
        el.get("name"): el.find("EffectLayer/Effect").get("ref")
        for el in root.findall("ElementEffects/Element")
    }
    assert db[int(by_element["A"])] == "Z_LAST=1,A_FIRST=2"
    assert db[int(by_element["B"])] == ""
```

Run: `.venv/Scripts/python -m pytest tests/test_xsq_writer.py -q`
Expected: failures in the layer-position, palette and settings-order tests.

- [ ] **Step 3: Implement in `xsq_writer.py`**

1. Import `DEFAULT_PALETTE`: `from xlights_mcp.xlights.palettes import DEFAULT_PALETTE, ColorPalette`.
2. Delete the `palettes: list[ColorPalette] = …` field from `SequenceSpec`.
3. Replace the `<ColorPalettes>` block (from `palettes_elem = …` through the `for ps in palette_strings` loop) with:

```python
    palettes_elem = ET.SubElement(root, "ColorPalettes")
    palette_index: dict[str, int] = {}
    for eff in spec.effects:
        palette_index.setdefault(_palette_string(eff), len(palette_index))
    for ps in palette_index:
        ET.SubElement(palettes_elem, "ColorPalette").text = ps
```

4. Replace the per-model layer loop (from `# Group by layer` down to the end of the palette `try/except`) with:

```python
        layers: dict[int, list[EffectPlacement]] = {}
        for eff in model_effects:
            layers.setdefault(eff.layer, []).append(eff)

        for layer_idx in range(max(layers, default=0) + 1):
            layer_elem = ET.SubElement(ee, "EffectLayer")
            for eff in sorted(layers.get(layer_idx, []), key=lambda e: e.start_time_ms):
                effect_elem = ET.SubElement(layer_elem, "Effect")
                effect_elem.set("name", eff.effect_name)
                effect_elem.set("startTime", str(eff.start_time_ms))
                effect_elem.set("endTime", str(eff.end_time_ms))
                effect_elem.set("ref", str(effect_settings_map[_build_effect_settings(eff)]))
                effect_elem.set("palette", str(palette_index[_palette_string(eff)]))
```

5. In `_build_effect_settings`, keep insertion order. The engine's dicts come from fixed tables, so equal settings still produce equal strings.

```python
def _build_effect_settings(eff: EffectPlacement) -> str:
    return ",".join(f"{key}={val}" for key, val in eff.settings.items())
```

6. Add:

```python
def _palette_string(eff: EffectPlacement) -> str:
    return (eff.palette or DEFAULT_PALETTE).to_xlights_string()
```

7. In `engine.py`, remove the `palettes=all_palettes,` argument from the `SequenceSpec(...)` call. Keep the other arguments on that line. `all_palettes` is still used elsewhere in the function, so leave the variable alone.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_xsq_writer.py tests/test_engine_write.py tests/test_engine_groups.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/xlights/xsq_writer.py src/xlights_mcp/sequencer/engine.py tests/test_xsq_writer.py tests/test_engine_write.py
git commit -m "write_xsq: palettes from placements, default palette, layer positions kept"
```

---

### Task 3: Known effect names and library reconciliation

**Files:**
- Modify: `src/xlights_mcp/xlights/effects.py`
- Test: `tests/test_effect_names.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""Effect names the writer accepts, and the library list_effects advertises."""

from __future__ import annotations

from pathlib import Path

from xlights_mcp.xlights.effects import (
    MODEL_EFFECT_MAP,
    MUSICAL_EFFECT_MAP,
    XLIGHTS_EFFECT_NAMES,
    get_effect_library,
    known_effect_names,
)


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


def _xsq(path: Path, body: str) -> None:
    path.write_text(f"<xsequence><ElementEffects>{body}</ElementEffects></xsequence>", encoding="utf-8")


def test_show_sequences_add_their_effect_names(tmp_path):
    _xsq(
        tmp_path / "a.xsq",
        '<Element type="model" name="X"><EffectLayer>'
        '<Effect ref="0" name="Custom Thing" startTime="0" endTime="25" palette="0"/>'
        "</EffectLayer></Element>",
    )

    assert "Custom Thing" in known_effect_names(tmp_path)
    assert "Custom Thing" not in known_effect_names(None)


def test_timing_marks_are_not_effect_names(tmp_path):
    _xsq(
        tmp_path / "a.xsq",
        '<Element type="timing" name="Beats"><EffectLayer>'
        '<Effect label="1" startTime="0" endTime="500"/>'
        "</EffectLayer></Element>",
    )

    assert known_effect_names(tmp_path) == XLIGHTS_EFFECT_NAMES
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_effect_names.py -q`
Expected: ImportError (`XLIGHTS_EFFECT_NAMES`).

- [ ] **Step 3: Implement**

At the top of `effects.py`, add `import re`, `from functools import lru_cache` and `from pathlib import Path`. After the imports:

```python
XLIGHTS_EFFECT_NAMES: frozenset[str] = frozenset({
    "Off", "On", "Adjust", "Bars", "Butterfly", "Candle", "Circles", "Color Wash", "Curtain",
    "DMX", "Duplicate", "Faces", "Fan", "Fill", "Fire", "Fireworks", "Galaxy", "Garlands",
    "Glediator", "Guitar", "Kaleidoscope", "Life", "Lightning", "Lines", "Liquid", "Marquee",
    "Meteors", "Morph", "Moving Head", "Music", "Piano", "Pictures", "Pinwheel", "Plasma",
    "Ripple", "Servo", "Shader", "Shape", "Shimmer", "Shockwave", "SingleStrand", "Sketch",
    "Snowflakes", "Snowstorm", "Spirals", "Spirograph", "State", "Strobe", "Tendril", "Text",
    "Tree", "Twinkle", "Video", "VU Meter", "Warp", "Wave",
})

_EFFECT_NAME = re.compile(rb'<Effect\b[^>]*?\bname="([^"]+)"')
```

Reconcile the library:
- Delete the `Chase` `EffectDef`. Add `"chorus"` to `SingleStrand`'s `musical_use`.
- Rename the `ColorWash` `EffectDef` to `name="Color Wash"`.
- In `MUSICAL_EFFECT_MAP` and `MODEL_EFFECT_MAP`, replace `"Chase"` with `"SingleStrand"`, removing the duplicate where a list then names it twice, and replace `"ColorWash"` with `"Color Wash"`.

At the end of the file:

```python
@lru_cache(maxsize=512)
def _effect_names_in(path: Path, mtime_ns: int, size: int) -> frozenset[str]:
    return frozenset(m.decode("utf-8", "replace") for m in _EFFECT_NAME.findall(path.read_bytes()))


def known_effect_names(show_path: Path | None) -> frozenset[str]:
    """XLIGHTS_EFFECT_NAMES plus every effect name used by the show folder's .xsq files."""
    names = set(XLIGHTS_EFFECT_NAMES)
    if show_path:
        for xsq in show_path.glob("*.xsq"):
            try:
                stat = xsq.stat()
                names |= _effect_names_in(xsq, stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
    return frozenset(names)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_effect_names.py tests/test_engine_groups.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/xlights/effects.py tests/test_effect_names.py
git commit -m "Known xLights effect names; list_effects advertises only real names"
```

---

### Task 4: Timing tracks

**Files:**
- Create: `src/xlights_mcp/sequencer/timing.py`
- Test: `tests/test_timing_tracks.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""Named timing tracks built from the analysis."""

from __future__ import annotations

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.stems_model import StemAnalysis, StemOnsets
from xlights_mcp.sequencer.timing import beat_labels, build_timing_tracks, to_frame


def test_to_frame_rounds_to_the_nearest_frame():
    assert [to_frame(v) for v in (1012, 1013, 1990, 0)] == [1000, 1025, 2000, 0]


def test_beat_labels_restart_at_each_downbeat():
    assert beat_labels([0.0, 0.5, 1.0, 1.5, 2.0, 2.5], [0.0, 2.0]) == ["1", "2", "3", "4", "1", "2"]


def test_a_partial_bar_before_a_reanchored_downbeat_is_short():
    assert beat_labels([0.0, 0.5, 1.0, 1.5, 2.0, 2.5], [0.0, 1.0]) == ["1", "2", "1", "2", "3", "4"]


def test_pickup_beats_count_back_to_four():
    assert beat_labels([0.0, 0.5, 1.0, 1.5], [1.0]) == ["3", "4", "1", "2"]


def test_without_downbeats_beats_count_in_fours():
    assert beat_labels([0.0, 0.5, 1.0, 1.5, 2.0], []) == ["1", "2", "3", "4", "1"]


def test_downbeats_match_beats_within_a_small_tolerance():
    assert beat_labels([0.0, 0.5, 1.0], [0.51]) == ["4", "1", "2"]


def _analysis(stems: bool = False) -> SongAnalysis:
    return SongAnalysis(
        file_path="song.mp3",
        file_name="song.mp3",
        duration_seconds=4.0,
        beats=BeatMap(
            tempo=120.0,
            beat_times=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
            downbeat_times=[0.0, 2.0],
        ),
        stem_analysis=StemAnalysis(
            available=stems,
            stems={"drums": StemOnsets(name="drums", onset_times=[0.51, 1.0, 1.005])} if stems else {},
        ),
    )


def _spans(track) -> list[tuple[str, int, int]]:
    return [(m.label, m.start_time_ms, m.end_time_ms) for m in track.labels[0]]


def test_beats_track_marks_run_to_the_next_beat_and_the_last_to_the_song_end():
    (track,), warnings, errors = build_timing_tracks(["Beats"], _analysis())

    assert track.name == "Beats" and warnings == [] and errors == []
    spans = _spans(track)
    assert [label for label, _, _ in spans] == ["1", "2", "3", "4", "1", "2", "3", "4"]
    assert spans[0] == ("1", 0, 500)
    assert spans[-1] == ("4", 3500, 4000)


def test_bars_track_numbers_the_downbeats():
    (track,), _, _ = build_timing_tracks(["Bars"], _analysis())

    assert _spans(track) == [("1", 0, 2000), ("2", 2000, 4000)]


def test_stem_track_uses_frame_rounded_onsets_and_collapses_same_frame_onsets():
    (track,), _, _ = build_timing_tracks(["Drums"], _analysis(stems=True))

    assert _spans(track) == [("x", 500, 1000), ("x", 1000, 4000)]


def test_stem_track_without_stems_is_skipped_with_a_warning():
    tracks, warnings, errors = build_timing_tracks(["Drums"], _analysis())

    assert tracks == [] and errors == []
    assert "Drums" in warnings[0]


def test_vocals_is_not_a_named_track():
    tracks, _, errors = build_timing_tracks(["Vocals"], _analysis())

    assert tracks == []
    assert "Vocals" in errors[0] and "lyrics" in errors[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_timing_tracks.py -q`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `src/xlights_mcp/sequencer/timing.py`**

```python
"""Frame-grid helpers and the named timing tracks built from a song analysis."""

from __future__ import annotations

import bisect
from collections.abc import Sequence

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.xlights.xsq_writer import TimingTrack, TimingTrackLabel

FRAME_MS = 25
BEATS_PER_BAR = 4
TIMING_TRACK_NAMES = ("Beats", "Bars", "Drums", "Bass", "Instruments")
_STEM_TRACKS = {"Drums": "drums", "Bass": "bass", "Instruments": "other"}
_DOWNBEAT_TOLERANCE_S = 0.05


def to_frame(ms: float, frame_ms: int = FRAME_MS) -> int:
    return int(round(ms / frame_ms)) * frame_ms


def last_frame_ms(duration_ms: int, frame_ms: int = FRAME_MS) -> int:
    return duration_ms - duration_ms % frame_ms


def _on_downbeat(t: float, downbeats: list[float]) -> bool:
    i = bisect.bisect_left(downbeats, t)
    return any(
        abs(t - downbeats[k]) < _DOWNBEAT_TOLERANCE_S for k in (i - 1, i) if 0 <= k < len(downbeats)
    )


def beat_labels(beat_times: Sequence[float], downbeat_times: Sequence[float]) -> list[str]:
    """Each beat's position in its bar: 1 on a downbeat, counting up; pickup beats count back to 4."""
    downbeats = sorted(downbeat_times)
    on_downbeat = [_on_downbeat(t, downbeats) for t in beat_times]
    first = next((i for i, down in enumerate(on_downbeat) if down), None)
    if first is None:
        return [str(i % BEATS_PER_BAR + 1) for i in range(len(beat_times))]
    labels = [str((i - first) % BEATS_PER_BAR + 1) for i in range(first)]
    position = 0
    for down in on_downbeat[first:]:
        position = 1 if down else position + 1
        labels.append(str(position))
    return labels


def _marks(times_s: Sequence[float], labels: Sequence[str], end_ms: int) -> list[TimingTrackLabel]:
    """Frame-rounded marks, each ending where the next starts; the last ends at end_ms."""
    points = sorted((to_frame(t * 1000), label) for t, label in zip(times_s, labels))
    marks = []
    for k, (start, label) in enumerate(points):
        end = min(points[k + 1][0] if k + 1 < len(points) else end_ms, end_ms)
        if start >= 0 and end > start:
            marks.append(TimingTrackLabel(label=label, start_time_ms=start, end_time_ms=end))
    return marks


def build_timing_tracks(
    names: Sequence[str], analysis: SongAnalysis
) -> tuple[list[TimingTrack], list[str], list[str]]:
    """(tracks, warnings, errors) for the requested named timing tracks."""
    end_ms = last_frame_ms(analysis.duration_ms)
    tracks: list[TimingTrack] = []
    warnings: list[str] = []
    errors: list[str] = []
    for name in names:
        if name == "Beats":
            beats = analysis.beats.beat_times
            marks = _marks(beats, beat_labels(beats, analysis.beats.downbeat_times), end_ms)
        elif name == "Bars":
            bars = analysis.beats.downbeat_times
            marks = _marks(bars, [str(i + 1) for i in range(len(bars))], end_ms)
        elif name in _STEM_TRACKS:
            stem_name = _STEM_TRACKS[name]
            stem = analysis.stem_analysis.stems.get(stem_name) if analysis.stem_analysis.available else None
            if stem is None or not stem.onset_times:
                warnings.append(f"{name} timing track skipped: no {stem_name} stem onsets (needs stem separation)")
                continue
            marks = _marks(stem.onset_times, ["x"] * len(stem.onset_times), end_ms)
        else:
            hint = " (the Vocals track comes from lyrics, not a stem)" if name == "Vocals" else ""
            errors.append(f"unknown timing track {name!r}; choose from {', '.join(TIMING_TRACK_NAMES)}{hint}")
            continue
        tracks.append(TimingTrack(name=name, labels=[marks]))
    return tracks, warnings, errors
```

Check the `to_frame` test by hand: 1012/25 = 40.48, which rounds to 40, giving 1000. 1013/25 = 40.52, which rounds to 41, giving 1025.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_timing_tracks.py -q`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/sequencer/timing.py tests/test_timing_tracks.py
git commit -m "Beats, Bars and stem-onset timing tracks from the analysis"
```

---

### Task 5: Transitive group membership

**Files:**
- Modify: `src/xlights_mcp/xlights/layout.py`
- Test: `tests/test_layout.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_layout.py`. Reuse the module's existing fixture-show loader; if there isn't one, call `load_show_config(Path(__file__).parent / "fixtures" / "show_groups")`. Add `contained_elements` to the `layout` import.

```python
def test_contained_elements_are_nested_groups_and_their_models():
    contained = contained_elements(load_show_config(Path(__file__).parent / "fixtures" / "show_groups"))

    assert contained["House"] == {
        "Roof Edges", "Under Roof", "Door",
        "Roof Left", "Roof Right", "Under Left", "Under Right", "Door L", "Door R",
    }
    assert contained["Cycle A"] == {"Cycle B", "Door L"}
    assert "Pipes" not in contained["House"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_layout.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement in `layout.py`**

```python
def contained_elements(show: ShowConfig) -> dict[str, frozenset[str]]:
    """Each group's nested groups (transitively) and the real models they reach."""
    groups = {g.name: g for g in show.model_groups}
    result = {}
    for name, group in groups.items():
        seen: set[str] = set()
        stack = list(group.child_groups)
        while stack:
            child = stack.pop()
            if child == name or child in seen:
                continue
            seen.add(child)
            stack.extend(groups[child].child_groups if child in groups else [])
        result[name] = frozenset(seen | set(group.leaf_models))
    return result
```

(`ShowConfig` is already imported in `layout.py`; if it isn't, import it from `xlights_mcp.xlights.models`.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_layout.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/xlights/layout.py tests/test_layout.py
git commit -m "contained_elements: transitive group membership"
```

---

### Task 6: Plan validation

**Files:**
- Create: `src/xlights_mcp/sequencer/plan.py`
- Test: `tests/test_plan_validation.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""validate_plan: one test per rule in the spec's rule table."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.sequencer.plan import validate_plan
from xlights_mcp.xlights.effects import XLIGHTS_EFFECT_NAMES
from xlights_mcp.xlights.show import load_show_config

SHOW = load_show_config(Path(__file__).parent / "fixtures" / "show_groups")


def _p(**over) -> dict:
    return {"element": "Door", "layer": 0, "effect": "On", "start_ms": 1000, "end_ms": 2000, **over}


def _validate(*placements, duration_ms: int = 20000):
    return validate_plan(list(placements), SHOW, duration_ms, XLIGHTS_EFFECT_NAMES)


def test_a_valid_placement_passes():
    result = _validate(_p())

    assert result.errors == [] and result.warnings == []
    (placement,) = result.placements
    assert (placement.model_name, placement.layer, placement.effect_name) == ("Door", 0, "On")
    assert (placement.start_time_ms, placement.end_time_ms) == (1000, 2000)


def test_models_and_groups_are_both_elements():
    assert _validate(_p(element="Pipes"), _p(element="Tree 6ft")).errors == []


def test_times_round_to_the_frame_grid():
    result = _validate(_p(start_ms=1012, end_ms=1990))

    assert (result.placements[0].start_time_ms, result.placements[0].end_time_ms) == (1000, 2000)
    assert result.adjusted == {"rounded_to_frame": 1, "clipped_to_end": 0}


def test_an_effect_past_the_song_end_is_clipped_to_the_last_frame():
    result = _validate(_p(start_ms=19000, end_ms=25000), duration_ms=20010)

    assert result.placements[0].end_time_ms == 20000
    assert result.adjusted["clipped_to_end"] == 1


@pytest.mark.parametrize("start, end", [(1000, 1010), (21000, 22000), (2000, 1000)])
def test_an_empty_span_after_rounding_or_clipping_is_an_error(start, end):
    result = _validate(_p(start_ms=start, end_ms=end))

    assert result.placements == []
    assert "ends at or before its start" in result.errors[0]


def test_negative_or_non_numeric_times_are_errors():
    assert "start_ms" in _validate(_p(start_ms=-25)).errors[0]
    assert "end_ms" in _validate(_p(end_ms="2s")).errors[0]


def test_errors_name_the_placement():
    assert _validate(_p(element="Nope")).errors[0].startswith("placement 0 ('Nope', layer 0, 1000-2000 ms): ")


def test_overlap_on_the_same_element_and_layer_is_an_error():
    result = _validate(_p(start_ms=0, end_ms=2000), _p(start_ms=1500, end_ms=3000))

    assert result.errors == [
        "placements 0 and 1 overlap on 'Door' layer 0: 0-2000 ms and 1500-3000 ms"
    ]


def test_touching_placements_and_other_layers_do_not_overlap():
    result = _validate(
        _p(start_ms=0, end_ms=2000), _p(start_ms=2000, end_ms=3000), _p(layer=1, start_ms=500, end_ms=2500)
    )

    assert result.errors == []


def test_every_placement_under_a_long_one_is_reported():
    result = _validate(_p(start_ms=0, end_ms=10000), _p(start_ms=1000, end_ms=2000), _p(start_ms=3000, end_ms=4000))

    assert len(result.errors) == 2


@pytest.mark.parametrize("layer", [-1, 3, "1", 1.0, True])
def test_a_layer_outside_0_to_2_is_an_error(layer):
    assert "layer must be an integer 0-2" in _validate(_p(layer=layer)).errors[0]


def test_an_unknown_element_suggests_close_names():
    error = _validate(_p(element="Lantern")).errors[0]

    assert "unknown element 'Lantern'" in error and "'Lanterns'" in error


def test_a_submodel_element_is_rejected():
    assert "submodel" in _validate(_p(element="Pipe 1/Top")).errors[0]


def test_an_unknown_effect_suggests_close_names():
    error = _validate(_p(effect="Colour Wash")).errors[0]

    assert "unknown effect 'Colour Wash'" in error and "'Color Wash'" in error


def test_effect_names_come_from_the_given_set():
    result = validate_plan([_p(effect="Custom Thing")], SHOW, 20000, XLIGHTS_EFFECT_NAMES | {"Custom Thing"})

    assert result.errors == []


def test_a_settings_map_keeps_its_order_and_writes_booleans_as_digits():
    result = _validate(_p(settings={"E_CHOICE_Chase_Type1": "Left-Right", "B_X": True, "E_N": 3}))

    assert list(result.placements[0].settings.items()) == [
        ("E_CHOICE_Chase_Type1", "Left-Right"), ("B_X", "1"), ("E_N", "3"),
    ]


def test_a_settings_value_with_a_comma_is_an_error():
    assert "comma" in _validate(_p(settings={"E_TEXTCTRL_Text": "a,b"})).errors[0]


def test_a_raw_settings_string_is_split_on_the_first_equals():
    result = _validate(_p(settings="E_A=1,E_VALUECURVE_B=Active=TRUE|Min=1|"))

    assert result.placements[0].settings == {"E_A": "1", "E_VALUECURVE_B": "Active=TRUE|Min=1|"}


@pytest.mark.parametrize("settings", ["E_A=1,oops", "=1", "E_A=1,E_A=2", 5])
def test_malformed_settings_are_errors(settings):
    assert "settings" in _validate(_p(settings=settings)).errors[0]


def test_a_palette_maps_colours_brightness_and_sparkles():
    result = _validate(_p(palette={"colors": ["#7fe7ff", "#00C8FF"], "brightness": 80, "sparkles": 30}))

    palette = result.placements[0].palette
    assert palette.colors == ["#7FE7FF", "#00C8FF"]
    assert palette.active_colors == [1, 2]
    assert (palette.brightness, palette.sparkle_frequency) == (80, 30)


def test_no_palette_leaves_the_default_to_the_writer():
    assert _validate(_p()).placements[0].palette is None


@pytest.mark.parametrize(
    "palette",
    [
        "red",
        {"colors": []},
        {"colors": ["red"]},
        {"colors": ["#FFF"]},
        {"colors": ["#FFFFFF"] * 9},
        {"colors": ["#FFFFFF"], "brightness": 401},
        {"colors": ["#FFFFFF"], "sparkles": -1},
    ],
)
def test_malformed_palettes_are_errors(palette):
    assert "palette" in _validate(_p(palette=palette)).errors[0]


def test_a_placement_must_be_an_object():
    assert "must be an object" in _validate("Door").errors[0]


def test_a_parent_lit_with_a_contained_element_is_a_warning():
    result = _validate(
        _p(element="House", start_ms=0, end_ms=4000),
        _p(element="Roof Edges", start_ms=1000, end_ms=2000),
        _p(element="Roof Left", start_ms=3000, end_ms=5000),
    )

    assert result.errors == []
    assert result.warnings == [
        "1 moment where House and Roof Edges are both lit",
        "1 moment where House and Roof Left are both lit",
    ]


def test_off_does_not_count_as_lit():
    result = _validate(_p(element="House", effect="Off", start_ms=0, end_ms=4000), _p(element="Roof Edges"))

    assert result.warnings == []


def test_parent_child_warnings_list_the_first_ten_pairs():
    pipes = [_p(element=f"Pipe {n}", start_ms=0, end_ms=1000) for n in range(1, 12)]

    result = _validate(_p(element="Everything Flat", start_ms=0, end_ms=1000), *pipes)

    assert len(result.warnings) == 11
    assert result.warnings[-1] == "... and 1 more parent/child pair lit together"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_plan_validation.py -q`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `src/xlights_mcp/sequencer/plan.py`**

```python
"""Validate an effect plan against the show and song before it is written."""

from __future__ import annotations

import difflib
import math
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from xlights_mcp.sequencer.timing import last_frame_ms, to_frame
from xlights_mcp.xlights.layout import contained_elements
from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.palettes import ColorPalette
from xlights_mcp.xlights.xsq_writer import EffectPlacement

MAX_LAYER = 2
PARENT_CHILD_PAIRS_LISTED = 10
_HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")


class PlanError(ValueError):
    """A placement that can't be written."""


@dataclass
class ValidatedPlan:
    placements: list[EffectPlacement] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adjusted: dict[str, int] = field(default_factory=lambda: {"rounded_to_frame": 0, "clipped_to_end": 0})


def validate_plan(
    plan: list, show: ShowConfig, duration_ms: int, effect_names: frozenset[str]
) -> ValidatedPlan:
    result = ValidatedPlan()
    elements = {m.name for m in show.models} | {g.name for g in show.model_groups}
    song_end = last_frame_ms(duration_ms)
    indexed: list[tuple[int, EffectPlacement]] = []
    for i, raw in enumerate(plan):
        try:
            placement, rounded, clipped = _placement(raw, elements, effect_names, song_end)
        except PlanError as e:
            result.errors.append(f"placement {i}{_describe(raw)}: {e}")
            continue
        result.adjusted["rounded_to_frame"] += rounded
        result.adjusted["clipped_to_end"] += clipped
        indexed.append((i, placement))
    result.errors.extend(_overlaps(indexed))
    result.warnings.extend(_parent_child_warnings([p for _, p in indexed], show))
    result.placements = [p for _, p in indexed]
    return result


def _describe(raw) -> str:
    if not isinstance(raw, dict):
        return ""
    return f" ({raw.get('element')!r}, layer {raw.get('layer', 0)}, {raw.get('start_ms')}-{raw.get('end_ms')} ms)"


def _placement(raw, elements, effect_names, song_end) -> tuple[EffectPlacement, bool, bool]:
    if not isinstance(raw, dict):
        raise PlanError("must be an object")
    element = _element(raw.get("element"), elements)
    layer = raw.get("layer", 0)
    if not _is_int(layer) or not 0 <= layer <= MAX_LAYER:
        raise PlanError(f"layer must be an integer 0-{MAX_LAYER}, got {layer!r}")
    effect = _effect(raw.get("effect"), effect_names)
    start, end, rounded, clipped = _times(raw.get("start_ms"), raw.get("end_ms"), song_end)
    placement = EffectPlacement(
        model_name=element,
        layer=layer,
        effect_name=effect,
        start_time_ms=start,
        end_time_ms=end,
        settings=_settings(raw.get("settings")),
        palette=_palette(raw.get("palette")),
    )
    return placement, rounded, clipped


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _suggest(name: str, choices: Iterable[str]) -> str:
    by_lower = {c.lower(): c for c in choices}
    close = difflib.get_close_matches(name.lower(), list(by_lower), n=3, cutoff=0.6)
    return f"; did you mean {', '.join(repr(by_lower[c]) for c in close)}?" if close else ""


def _element(name, elements: set[str]) -> str:
    if not isinstance(name, str) or not name:
        raise PlanError("element is required")
    if name in elements:
        return name
    if "/" in name:
        raise PlanError(f"{name!r} is a submodel; submodel elements aren't supported yet, use a group")
    raise PlanError(f"unknown element {name!r}{_suggest(name, elements)}")


def _effect(name, effect_names: frozenset[str]) -> str:
    if not isinstance(name, str) or not name:
        raise PlanError("effect is required")
    if name in effect_names:
        return name
    raise PlanError(f"unknown effect {name!r}{_suggest(name, effect_names)}")


def _times(start, end, song_end: int) -> tuple[int, int, bool, bool]:
    for key, value in (("start_ms", start), ("end_ms", end)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise PlanError(f"{key} must be a number of milliseconds, got {value!r}")
    if start < 0:
        raise PlanError(f"start_ms must be >= 0, got {start}")
    frame_start, frame_end = to_frame(start), to_frame(end)
    rounded = (frame_start, frame_end) != (start, end)
    clipped = frame_end > song_end
    frame_end = min(frame_end, song_end)
    if frame_end <= frame_start:
        raise PlanError(f"ends at or before its start after rounding/clipping ({frame_start}-{frame_end} ms)")
    return frame_start, frame_end, rounded, clipped


def _settings(value) -> dict[str, str]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        pairs = [(k, str(int(v)) if isinstance(v, bool) else str(v)) for k, v in value.items()]
        for key, text in pairs:
            if "," in text:
                raise PlanError(f"settings value for {key} contains a comma; xLights separates settings with commas")
    elif isinstance(value, str):
        pairs = []
        for part in value.split(","):
            key, sep, text = part.partition("=")
            if not sep:
                raise PlanError(f"malformed settings part {part!r}; expected KEY=VALUE")
            pairs.append((key, text))
    else:
        raise PlanError("settings must be an object or a 'KEY=VALUE,KEY=VALUE' string")
    settings: dict[str, str] = {}
    for key, text in pairs:
        if not key or "," in key or "=" in key:
            raise PlanError(f"invalid settings key {key!r}")
        if key in settings:
            raise PlanError(f"settings key {key} appears twice")
        settings[key] = text
    return settings


def _palette(value) -> ColorPalette | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PlanError("palette must be an object")
    colors = value.get("colors")
    if not isinstance(colors, list) or not 1 <= len(colors) <= 8:
        raise PlanError("palette.colors must list 1-8 colours")
    bad = next((c for c in colors if not (isinstance(c, str) and _HEX_COLOUR.fullmatch(c))), None)
    if bad is not None:
        raise PlanError(f"palette colours must be #RRGGBB, got {bad!r}")
    return ColorPalette(
        colors=[c.upper() for c in colors],
        active_colors=list(range(1, len(colors) + 1)),
        brightness=_palette_int(value, "brightness", 100, 400),
        sparkle_frequency=_palette_int(value, "sparkles", 0, 200),
    )


def _palette_int(palette: dict, key: str, default: int, upper: int) -> int:
    value = palette.get(key, default)
    if not _is_int(value) or not 0 <= value <= upper:
        raise PlanError(f"palette.{key} must be an integer 0-{upper}, got {value!r}")
    return value


def _overlaps(indexed: list[tuple[int, EffectPlacement]]) -> list[str]:
    by_track: dict[tuple[str, int], list[tuple[int, EffectPlacement]]] = defaultdict(list)
    for i, p in indexed:
        by_track[(p.model_name, p.layer)].append((i, p))
    errors = []
    for (element, layer), items in by_track.items():
        items.sort(key=lambda item: item[1].start_time_ms)
        prev_i, prev = items[0]
        for i, p in items[1:]:
            if p.start_time_ms < prev.end_time_ms:
                a, b = sorted(((prev_i, prev), (i, p)), key=lambda item: item[0])
                errors.append(
                    f"placements {a[0]} and {b[0]} overlap on {element!r} layer {layer}: "
                    f"{a[1].start_time_ms}-{a[1].end_time_ms} ms and {b[1].start_time_ms}-{b[1].end_time_ms} ms"
                )
            if p.end_time_ms > prev.end_time_ms:
                prev_i, prev = i, p
    return errors


def _parent_child_warnings(placements: list[EffectPlacement], show: ShowConfig) -> list[str]:
    lit: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for p in placements:
        if p.effect_name != "Off":
            lit[p.model_name].append((p.start_time_ms, p.end_time_ms))
    counts: dict[tuple[str, str], int] = {}
    for parent, members in contained_elements(show).items():
        if parent not in lit:
            continue
        for child in members & lit.keys():
            n = sum(1 for s1, e1 in lit[parent] for s2, e2 in lit[child] if s1 < e2 and s2 < e1)
            if n:
                counts[(parent, child)] = n
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    warnings = [
        f"{n} moment{'s' if n != 1 else ''} where {parent} and {child} are both lit"
        for (parent, child), n in ranked[:PARENT_CHILD_PAIRS_LISTED]
    ]
    extra = len(ranked) - PARENT_CHILD_PAIRS_LISTED
    if extra > 0:
        warnings.append(f"... and {extra} more parent/child pair{'s' if extra != 1 else ''} lit together")
    return warnings
```

Check the tests against this code:
- **`(2000, 1000)`:** start 2000, end 1000 gives `frame_end <= frame_start`, so an error. ✓
- **`(21000, 22000)` with a 20000 song end:** the end clips to 20000, which is before 21000, so an error. ✓
- **Overlap test:** items are sorted by start and the pair is reported in index order, so the message reads `placements 0 and 1`. ✓
- **Parent/child test:** House contains Roof Edges and Roof Left. Roof Edges also contains Roof Left, but those two don't overlap in time. The sort key `(-n, (parent, child))` puts `("House", "Roof Edges")` before `("House", "Roof Left")`. ✓
- **Pipes test:** Everything Flat plus 11 pipes gives 11 pairs, so 10 are listed plus 1 summary line: 11 warnings. ✓

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_plan_validation.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/sequencer/plan.py tests/test_plan_validation.py
git commit -m "validate_plan: frame rounding, clipping, overlaps, names, settings, palettes"
```

---

### Task 7: `write_plan`

**Files:**
- Create: `src/xlights_mcp/sequencer/plan_writer.py`
- Test: `tests/test_plan_writer.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""write_plan: validation report, output path rules and the written file."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.sequencer.plan_writer import MAX_REPORTED_ERRORS, write_plan
from xlights_mcp.xlights.xsq_writer import TimingTrack

FIXTURE = Path(__file__).parent / "fixtures" / "show_groups"
ANALYSIS = SongAnalysis(
    file_path="Song.mp3",
    file_name="Song.mp3",
    duration_seconds=8.0,
    beats=BeatMap(tempo=120.0, beat_times=[i * 0.5 for i in range(16)], downbeat_times=[0.0, 2.0, 4.0, 6.0]),
)
PLAN = [
    {"element": "House", "layer": 0, "effect": "Color Wash", "start_ms": 0, "end_ms": 4000},
    {"element": "Lanterns", "layer": 1, "effect": "On", "start_ms": 2000, "end_ms": 2100,
     "palette": {"colors": ["#FF6600"], "brightness": 150}},
]


@pytest.fixture
def show(tmp_path: Path) -> Path:
    folder = tmp_path / "show"
    folder.mkdir()
    shutil.copy(FIXTURE / "xlights_rgbeffects.xml", folder)
    return folder


def _write(show: Path, plan=PLAN, **kw) -> dict:
    return write_plan(plan, ANALYSIS, Path("C:/music/Song.mp3"), show, **kw)


def test_writes_the_sequence_and_reports_it(show):
    report = _write(show, timing_tracks=["Beats", "Bars"])

    assert report["errors"] == [] and report["written"] is True
    assert report["path"] == str(show / "Song.xsq")
    assert (report["elements"], report["effects"], report["max_layer"]) == (2, 2, 1)
    assert report["timing_tracks"] == ["Beats", "Bars"]
    root = ET.parse(show / "Song.xsq").getroot()
    lantern_layers = root.findall("ElementEffects/Element[@name='Lanterns']/EffectLayer")
    assert [len(layer) for layer in lantern_layers] == [0, 1]
    assert any("C_SLIDER_Brightness=150" in (p.text or "") for p in root.findall("ColorPalettes/ColorPalette"))
    beats = root.find("ElementEffects/Element[@name='Beats']/EffectLayer")
    assert [m.get("label") for m in beats][:5] == ["1", "2", "3", "4", "1"]


def test_validate_only_writes_nothing(show):
    report = _write(show, validate_only=True)

    assert report["errors"] == [] and report["written"] is False
    assert not (show / "Song.xsq").exists()


def test_errors_abort_the_write(show):
    report = _write(show, plan=[{**PLAN[0], "element": "Nope"}])

    assert report["written"] is False and report["errors"]
    assert not (show / "Song.xsq").exists()


def test_an_existing_file_needs_overwrite(show):
    (show / "Song.xsq").write_text("old", encoding="utf-8")

    refused = _write(show)
    replaced = _write(show, overwrite=True)

    assert refused["written"] is False and "overwrite" in refused["errors"][0]
    assert replaced["written"] is True
    assert (show / "Song.xsq").read_text(encoding="utf-8") != "old"


def test_name_sets_the_file_name_and_rejects_paths(show):
    assert _write(show, name="My Show")["path"] == str(show / "My Show.xsq")
    assert "name" in _write(show, name="../escape")["errors"][0]


def test_duplicate_timing_track_names_are_an_error(show):
    extra = TimingTrack(name="Beats", labels=[[]])

    report = _write(show, timing_tracks=["Beats"], extra_tracks=[extra])

    assert any("Beats" in e and "more than once" in e for e in report["errors"])


def test_never_writes_a_backup(show):
    _write(show)

    assert list(show.glob("*.xbkp")) == []


def test_effect_names_used_in_the_show_are_accepted(show):
    (show / "Other.xsq").write_text(
        '<xsequence><ElementEffects><Element type="model" name="X"><EffectLayer>'
        '<Effect ref="0" name="Future Effect" startTime="0" endTime="25" palette="0"/>'
        "</EffectLayer></Element></ElementEffects></xsequence>",
        encoding="utf-8",
    )

    report = _write(show, plan=[{**PLAN[0], "effect": "Future Effect"}], validate_only=True)

    assert report["errors"] == []


def test_the_error_list_is_capped(show):
    plan = [{**PLAN[0], "element": f"Nope {i}"} for i in range(MAX_REPORTED_ERRORS + 5)]

    report = _write(show, plan=plan)

    assert len(report["errors"]) == MAX_REPORTED_ERRORS + 1
    assert report["errors"][-1] == "... and 5 more errors"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_plan_writer.py -q`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `src/xlights_mcp/sequencer/plan_writer.py`**

```python
"""Validate an effect plan and write it as an .xsq (the internals behind write_sequence)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.sequencer.plan import validate_plan
from xlights_mcp.sequencer.timing import build_timing_tracks
from xlights_mcp.xlights.effects import known_effect_names
from xlights_mcp.xlights.show import load_show_config
from xlights_mcp.xlights.xsq_writer import SequenceSpec, TimingTrack, write_xsq

MAX_REPORTED_ERRORS = 50


def write_plan(
    plan: list,
    analysis: SongAnalysis,
    mp3_path: Path,
    show_path: Path,
    name: str | None = None,
    timing_tracks: Sequence[str] = (),
    extra_tracks: Sequence[TimingTrack] = (),
    overwrite: bool = False,
    validate_only: bool = False,
) -> dict:
    show = load_show_config(show_path)
    validated = validate_plan(plan, show, analysis.duration_ms, known_effect_names(show_path))
    tracks, track_warnings, errors = build_timing_tracks(timing_tracks, analysis)
    tracks = [*tracks, *extra_tracks]
    errors = validated.errors + errors
    errors += [
        f"timing track {track!r} appears more than once"
        for track, n in Counter(t.name for t in tracks).items() if n > 1
    ]

    file_name = f"{name or mp3_path.stem}.xsq"
    output = show_path / file_name
    if name is not None and (not name.strip() or Path(file_name).name != file_name):
        errors.append(f"name must be a plain file name without folders, got {name!r}")
    elif output.exists() and not overwrite:
        errors.append(f"{file_name} already exists; pass overwrite=true to replace it")

    placements = validated.placements
    report = {
        "path": str(output),
        "written": False,
        "elements": len({p.model_name for p in placements}),
        "effects": len(placements),
        "max_layer": max((p.layer for p in placements), default=0),
        "timing_tracks": [t.name for t in tracks],
        "adjusted": validated.adjusted,
        "errors": _capped(errors),
        "warnings": validated.warnings + track_warnings,
    }
    if errors or validate_only:
        return report

    spec = SequenceSpec(
        song_title=mp3_path.stem,
        media_file=str(mp3_path),
        duration_ms=analysis.duration_ms,
        effects=placements,
        timing_tracks=tracks,
    )
    write_xsq(spec, show, output)
    report["written"] = True
    return report


def _capped(errors: list[str]) -> list[str]:
    if len(errors) <= MAX_REPORTED_ERRORS:
        return errors
    return [*errors[:MAX_REPORTED_ERRORS], f"... and {len(errors) - MAX_REPORTED_ERRORS} more errors"]
```

Notes:
- `Path("../escape.xsq").name` is `"escape.xsq"`, which differs from the full name, so it is an error. `Path("My Show.xsq").name` is unchanged, so it is accepted. On Windows, `Path("a\\b.xsq").name == "b.xsq"` is also caught.
- `write_xsq` opens the output file with `"w"`, which overwrites in place. Nothing creates a `.xbkp`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_plan_writer.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/sequencer/plan_writer.py tests/test_plan_writer.py
git commit -m "write_plan: validate, choose the output path and write the sequence"
```

---

### Task 8: `write_sequence` MCP tool and README

**Files:**
- Modify: `src/xlights_mcp/server.py`. Add `import json` to the imports, and put the tool right after `create_sequence` in the *Sequence Generation Tools* section.
- Modify: `README.md` (the *Sequence Generation* table)
- Test: `tests/test_write_sequence_tool.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""write_sequence through an in-memory MCP session."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from xlights_mcp import server as server_module
from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.cache import save_cached
from xlights_mcp.config import AudioConfig, ServerConfig

FIXTURE = Path(__file__).parent / "fixtures" / "show_groups"
PLAN = [{"element": "Door", "layer": 0, "effect": "On", "start_ms": 0, "end_ms": 1000}]


@pytest.fixture
def show(tmp_path: Path, click_track: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "show"
    folder.mkdir()
    shutil.copy(FIXTURE / "xlights_rgbeffects.xml", folder)
    config = ServerConfig(
        show_folders={"fixture": str(folder)},
        active_show="fixture",
        audio=AudioConfig(cache_dir=tmp_path / "cache"),
    )
    monkeypatch.setattr(server_module, "_config", config)
    save_cached(
        SongAnalysis(
            file_path=str(click_track),
            file_name=click_track.name,
            duration_seconds=3.0,
            beats=BeatMap(tempo=120.0, beat_times=[0.0, 0.5, 1.0, 1.5], downbeat_times=[0.0]),
        ),
        click_track,
        config.audio.cache_dir,
    )
    return folder


async def _call(args: dict) -> dict:
    async with create_connected_server_and_client_session(server_module.mcp) as client:
        result = await client.call_tool("write_sequence", args)
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


async def test_writes_a_plan_into_the_active_show(show, click_track):
    report = await _call({"mp3_path": str(click_track), "plan": PLAN, "timing_tracks": ["Beats"]})

    assert report["written"] is True and report["errors"] == []
    assert Path(report["path"]) == show / f"{click_track.stem}.xsq"


async def test_plan_path_resolves_against_the_show_folder(show, click_track):
    (show / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")

    report = await _call({"mp3_path": str(click_track), "plan_path": "plan.json", "validate_only": True})

    assert report["errors"] == [] and report["effects"] == 1


@pytest.mark.parametrize("args", [{}, {"plan": PLAN, "plan_path": "plan.json"}])
async def test_exactly_one_plan_source_is_required(show, click_track, args):
    payload = await _call({"mp3_path": str(click_track), **args})

    assert "exactly one" in payload["error"]


async def test_an_unreadable_plan_file_is_an_error(show, click_track):
    (show / "bad.json").write_text("{not json", encoding="utf-8")

    payload = await _call({"mp3_path": str(click_track), "plan_path": "bad.json"})

    assert "bad.json" in payload["error"]


async def test_a_plan_file_must_hold_a_list(show, click_track):
    (show / "obj.json").write_text("{}", encoding="utf-8")

    payload = await _call({"mp3_path": str(click_track), "plan_path": "obj.json"})

    assert "list" in payload["error"]


async def test_a_missing_song_is_an_error(show, tmp_path):
    payload = await _call({"mp3_path": str(tmp_path / "missing.mp3"), "plan": PLAN})

    assert "not found" in payload["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_write_sequence_tool.py -q`
Expected: failures (unknown tool `write_sequence`).

- [ ] **Step 3: Implement the tool in `server.py`**

```python
@mcp.tool()
async def write_sequence(
    mp3_path: str,
    ctx: Context,
    plan: list[dict] | None = None,
    plan_path: str | None = None,
    name: str | None = None,
    timing_tracks: list[str] | None = None,
    overwrite: bool = False,
    validate_only: bool = False,
) -> dict:
    """Validate an effect plan against the active show and the song, then write it as an .xsq.

    Each placement: {"element", "layer", "effect", "start_ms", "end_ms", "settings", "palette"}.
    - element: a model or group name (list_models / get_show_layout); submodels aren't supported.
    - layer: 0-2 (default 0). effect: an xLights effect name (list_effects, or any effect
      already used in this show's sequences).
    - settings: {key: value} (values can't contain commas) or a raw "K=V,K=V" string.
    - palette: {"colors": ["#RRGGBB", ...] (1-8), "brightness": 0-400 (default 100),
      "sparkles": 0-200 (default 0)}; omitted means a white palette.

    Times are rounded to the 25 ms frame grid and clipped to the song end (counted under
    "adjusted"). Any error writes nothing: overlapping placements on the same element and layer,
    a bad layer, an unknown element or effect, malformed settings or palette, an unknown or
    duplicate timing track, or an existing file without overwrite. A group lit while a group or
    model inside it is also lit is a warning. The report lists at most 50 errors.

    Args:
        mp3_path: The song; analysed first when it isn't cached (like get_beat_map)
        plan: The placements. Pass this or plan_path, not both.
        plan_path: A JSON file holding the placement list; relative paths resolve against
            the active show folder
        name: Sequence file name without .xsq (default: the song's file name)
        timing_tracks: Any of "Beats" (labelled with the beat's position in its bar), "Bars"
            (numbered), "Drums", "Bass", "Instruments" (stem onsets; need stem separation).
            Effects can reference them, e.g. E_CHOICE_VUMeter_TimingTrack=Beats.
        overwrite: Replace an existing .xsq with the same name
        validate_only: Run every check and return the report without writing
    """
    from xlights_mcp.sequencer.plan_writer import write_plan

    config = get_config()
    show_path = config.active_show_path
    if not show_path or not show_path.exists():
        return {
            "error": "No active show folder configured.",
            "action_required": "Ask the user for the path to their xLights show directory and call add_show_folder.",
        }
    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}
    if (plan is None) == (plan_path is None):
        return {"error": "Pass exactly one of plan or plan_path."}
    if plan_path is not None:
        plan_file = Path(plan_path).expanduser()
        if not plan_file.is_absolute():
            plan_file = show_path / plan_file
        try:
            plan = json.loads(plan_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            return {"error": f"Could not read plan file {plan_file}: {e}"}
        if not isinstance(plan, list):
            return {"error": f"Plan file {plan_file} must hold a list of placements."}

    analysis = await _analyze_in_thread(path, ctx)
    return await anyio.to_thread.run_sync(
        lambda: write_plan(
            plan,
            analysis,
            path,
            show_path,
            name=name,
            timing_tracks=timing_tracks or [],
            overwrite=overwrite,
            validate_only=validate_only,
        )
    )
```

(`json.JSONDecodeError` is a subclass of `ValueError`, and so is `UnicodeDecodeError`, so both are caught.)

README: add this row after `create_sequence` in the *Sequence Generation* table:

```markdown
| `write_sequence` | Validate an effect plan (element, layer 0–2, effect, times, settings, palette) against the show and song, then write it as an `.xsq`, with optional Beats/Bars/stem timing tracks; `validate_only` returns the report without writing |
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_write_sequence_tool.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/server.py README.md tests/test_write_sequence_tool.py
git commit -m "write_sequence MCP tool"
```

---

### Task 9: Full verification on the real show

**Files:** none (the checks run against copies in the scratchpad).

- [ ] **Step 1: Full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: every test passes (about 319 + ~70 new), 1 deselected.

- [ ] **Step 2: Real-show smoke test (Halloween, into a scratch copy of the show)**

Write the script below to the session scratchpad, then run it with `.venv/Scripts/python <script>`. It uses the cached analysis of `GhostsnStuffft.RobSwire.mp3` (it was analysed earlier this session; if the cache misses, the full pipeline runs, which takes a few minutes). It writes into a scratch copy, never into `E:\XLights\HalloweenShow` itself.

```python
import shutil, tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xlights_mcp.audio.analyzer import full_analysis
from xlights_mcp.config import load_config
from xlights_mcp.sequencer.plan_writer import write_plan

song = Path(r"E:\XLights\HalloweenShow\Music\GhostsnStuffft.RobSwire.mp3")
show = Path(tempfile.mkdtemp()) / "HalloweenShow"
show.mkdir()
shutil.copy(r"E:\XLights\HalloweenShow\xlights_rgbeffects.xml", show)
for xsq in Path(r"E:\XLights\HalloweenShow").glob("*.xsq"):
    shutil.copy(xsq, show)
analysis = full_analysis(song, load_config().audio)
plan = [
    {"element": "House", "layer": 0, "effect": "Color Wash", "start_ms": 0, "end_ms": 16000,
     "palette": {"colors": ["#FF6600", "#800080"], "brightness": 60}},
    {"element": "Spooky Fence", "layer": 0, "effect": "SingleStrand", "start_ms": 16000, "end_ms": 32000,
     "settings": {"E_CHOICE_Chase_Type1": "Left-Right", "E_NOTEBOOK_SSEFFECT_TYPE": "Chase"}},
    {"element": "Lanterns", "layer": 1, "effect": "On", "start_ms": 16000, "end_ms": 16100},
    {"element": "Roof Edges", "layer": 2, "effect": "Shockwave", "start_ms": 20000, "end_ms": 21000},
]
report = write_plan(plan, analysis, song, show, name="MCP writer smoke",
                    timing_tracks=["Beats", "Bars", "Drums", "Bass", "Instruments"])
print(report)
root = ET.parse(report["path"]).getroot()
print([len(l) for l in root.findall("ElementEffects/Element[@name='Roof Edges']/EffectLayer")])
```

Expected:
- `errors == []` and `written: True`.
- One warning about House and Roof Edges.
- Roof Edges layers print as `[0, 0, 1]`.
- Five timing tracks when stems are cached.

If any group name above doesn't exist in the real show, the report's suggestions show the right name. Fix the plan and rerun; don't change the code for it.

- [ ] **Step 3: Report**

Give the user the scratch `.xsq` path so they can open it in xLights. Check that the layer, palette and timing tracks look right. Don't push or open the PR until the user asks, unless they already said to open it once review passes.
