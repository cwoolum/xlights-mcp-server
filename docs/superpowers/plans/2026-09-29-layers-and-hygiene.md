# Layer order, blend modes and output hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the quick items from `E:\XLights\mcp-sharp-edges.md`, ranked table rows 3 and 7, plus the layer-order findings:
- say that layer 0 is drawn on top, and warn when a base hides the layers beneath it;
- add blend modes, value-curve units and music sparkles;
- write only the elements a sequence uses;
- stamp the installed xLights version into the file.

**Architecture:** these are small changes to existing modules. `plan.py` gains the `blend` and `music_sparkles` fields and a layer-cover warning. `xsq_writer.py` gains the element pruning and the version stamp. A new `xlights/version.py` detects the installed version. `engine.py` changes its face layering, and the playbook and docstrings get documentation.

**Tech Stack:** Python 3.12, pydantic v2, FastMCP (mcp<2), pytest.

---

## Ground rules

- **Branch:** `fix/layers-and-hygiene`, created from `main`. Don't rebase, switch branches or push.
- **Python:** `.venv/Scripts/python` only. Never `uv run`, `uv sync` or `uv pip install`.
- **Tests:** `.venv/Scripts/python -m pytest <path> -q`. Baseline: 518 passed, 1 deselected.
- **Commits:** one per task. Stage only the named paths with `git add <paths>`, then `git commit`. End each commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never `git commit -a`, `git add .`, `-A`, or `git stash`. Leave the untracked `uv.lock` alone.
- **Code style:** no comments that restate code. Keep CRLF line endings where files already have them.
- **TDD:** write the failing test first and watch it fail.

## Domain facts, checked against the user's sequences

- **Layer order.** xLights draws an element's first `<EffectLayer>` (its "Layer 1") on top. `write_sequence` writes placement layer 0 first, so **layer 0 is on top**. A full-coverage effect with Normal blending (Color Wash, Plasma, solid On) on a lower layer number hides everything on higher layer numbers while they overlap.
- **Blend mode.** The key is `T_CHOICE_LayerMethod` in the effect settings, and it applies to the upper layer (Effect 1 = this layer, Effect 2 = the layers below). Valid values, in xLights' own list order: `Normal`, `Effect 1`, `Effect 2`, `1 is Mask`, `2 is Mask`, `1 is Unmask`, `2 is Unmask`, `1 is True Unmask`, `2 is True Unmask`, `1 reveals 2`, `2 reveals 1`, `Shadow 1 on 2`, `Shadow 2 on 1`, `Layered`, `Average`, `Bottom-Top`, `Left-Right`, `Additive`, `Subtractive`, `Brightness`, `Max`, `Min`. The user's sequences use Additive 221 times, Layered 54, then 2 is Unmask, Effect 1, 2 is Mask, 1 reveals 2, 2 reveals 1, 1 is True Unmask, Max, Average, 1 is Unmask, Effect 2, Subtractive, Bottom-Top and 1 is Mask. Normal is the default; when it's Normal, xLights omits the key.
- **Music sparkles.** `C_CHECKBOX_MusicSparkles=1` in the palette string (used 60 times). It is separate from `C_SLIDER_SparkleFrequency`.
- **Value curves.** With `RV=TRUE`, `P1`/`P2`/`Min`/`Max` are real values in the setting's own units, not percentages. Examples: Wave speed ×100, so `Max=5000`; palette brightness 0–400; Bars count 1–5. A brightness ramp inside one effect works as `C_VALUECURVE_Brightness=…` in `settings`, because xLights merges effect settings and palette into one render map. Custom curve points snap to 1/200 of the effect's length.
- **Installed version.** On Windows it's the uninstall registry entry `xLights version 2026.17`, with `DisplayVersion` = `2026.17`, under `HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\*` (or the `WOW6432Node` equivalent). The generator currently hard-codes `2025.13`, which makes xLights migrate settings on its first save.

---

### Task 1: `blend` on placements, `music_sparkles` on palettes

**Files:**
- `src/xlights_mcp/sequencer/plan.py`
- `src/xlights_mcp/xlights/palettes.py`
- `tests/test_plan_validation.py`
- `tests/test_palettes.py`

1. **`palettes.py`:**
   - `ColorPalette` gains `music_sparkles: bool = False`.
   - `to_xlights_string` appends `C_CHECKBOX_MusicSparkles=1` when it's true, right after the sparkle-frequency part.
   - Test: the string includes the checkbox when set and omits it by default.
2. **`plan.py`:**
   - Add `BLEND_MODES: tuple[str, ...]` holding the 22 values above, in order.
   - Add `"blend"` to `_PLACEMENT_KEYS` and `"music_sparkles"` to `_PALETTE_KEYS`.
   - `blend` must be one of `BLEND_MODES`. Otherwise it's an error with `_suggest` suggestions, matched case-insensitively, e.g. "unknown blend 'additive'; did you mean 'Additive'?". Better still, accept an exact case-insensitive match and normalise it to the canonical spelling. Test both.
   - A non-`Normal` blend sets `settings["T_CHOICE_LayerMethod"] = blend`. `Normal` sets nothing.
   - Giving both `blend` and `T_CHOICE_LayerMethod` in `settings` is an error: "use blend or T_CHOICE_LayerMethod, not both".
   - `music_sparkles` must be a real bool; anything else is an error.
3. Commit: "Placements take a blend mode; palettes take music_sparkles".

### Task 2: warn when a top layer hides the layers below

**Files:**
- `src/xlights_mcp/sequencer/plan.py`
- `tests/test_plan_validation.py`

1. Add `FULL_COVERAGE_EFFECTS = frozenset({"Color Wash", "Plasma", "On"})`.
2. Let `p` be a placement on element E and layer L whose effect is in that set, whose blend is Normal (no `T_CHOICE_LayerMethod`, or it equals `Normal`), and that isn't `Off`. For each such `p`, count the placements `q` on the same element with `q.layer > L` that overlap `p` in time. Aggregate the counts per (element, upper layer, lower layer).
3. Emit one warning per group, listed and capped the same way as the parent/child warnings (reuse the helper or the constant). The text:
   `"{n} moment(s) where {effect} on {element} layer {L} hides layer {M} (layer 0 is drawn on top: put bases on the highest layer, or give the upper effect a blend)"`.
   When several effects hit the same (element, L, M), use the first effect's name.
4. Tests:
   - A Color Wash on layer 0 over an On on layer 1 of the same element gives a warning.
   - The same pair with `blend: "Additive"` on the wash gives none.
   - A wash on layer 1 under an accent on layer 0 gives none.
   - Two elements don't interact.
5. Commit: "Warn when a full-coverage effect on a top layer hides the layers below".

### Task 3: write only the used elements; stamp the installed xLights version

**Files:**
- `src/xlights_mcp/xlights/xsq_writer.py`
- `src/xlights_mcp/xlights/version.py` (new)
- `src/xlights_mcp/sequencer/plan_writer.py`
- `tests/test_xsq_writer.py`
- `tests/test_xlights_version.py` (new)
- Also fix any test that assumed every show model is listed.

1. **`write_xsq`:**
   - DisplayElements and ElementEffects list only the elements that have placements. Timing tracks still come first.
   - Order the model elements the way the show file does: groups in `show_config.model_groups` order first, then models in `show_config.models` order. Names not in the show come last, sorted.
   - First grep `src/` for other callers of `write_xsq`, such as the remapper, and check none relies on the old list-everything behaviour.
   - Tests:
     - A 1-effect sequence on a show with many models lists exactly one model element.
     - The order follows the show.
2. **`SequenceSpec`** gains `xlights_version: str = DEFAULT_XLIGHTS_VERSION` (`"2025.13"`), and the head's `<version>` uses it.
3. **New `xlights/version.py`** with `installed_xlights_version(show_path: Path | None = None) -> str`:
   - On Windows (`sys.platform == "win32"`), read the uninstall registry (`winreg`; both hives and both `Uninstall` roots). Find the entry whose `DisplayName` starts with `xLights` and return its `DisplayVersion`.
   - Otherwise, or when that fails, return the highest `<version>` found in the first 4 KB of the show folder's `.xsq` files. Compare versions as `(year, minor)` integer tuples.
   - Otherwise return `DEFAULT_XLIGHTS_VERSION`.
   - Cache the registry lookup with `functools.lru_cache`.
   - Catch `OSError` and `ValueError`; never raise.
   - Tests: monkeypatch the registry reader, then check the show-folder fallback picks the highest version, then check the default. Keep the tests platform-independent by monkeypatching `sys.platform` and the reader function.
4. **`write_plan`** passes `xlights_version=installed_xlights_version(show_path)` into `SequenceSpec`.
   - Test: the written head carries the patched version.
5. Commit: "Write only the elements a sequence uses; stamp the installed xLights version".

### Task 4: face layering, playbook and docstrings

**Files:**
- `src/xlights_mcp/sequencer/engine.py`
- `src/xlights_mcp/prompts/sequence_song.md`
- `src/xlights_mcp/server.py` (the `write_sequence` docstring)
- `README.md`
- `tests/test_engine_auto.py`
- `tests/test_sequence_song_prompt.py`

1. **Singing faces in `engine.py`:** put the `Faces` effect on **layer 0** (on top) and the section bed on **layer 1**. Update the tests that assert layers. Add an assertion that the Faces effect is in the first `EffectLayer` of the singing model in the written file.
2. **`sequence_song.md`:**
   - **Step 4:**
     - Replace "Use at most 3 layers (0–2) per element; most elements need only layer 0" with: "Use at most 3 layers (0–2). **Layer 0 is drawn on top**: put accents on layer 0 and bases (wash, Plasma, solid colour) on the highest layer you use. `write_sequence` warns when a base on a top layer hides what's below."
     - Rephrase the wash-base bullet so "base" doesn't imply layer 0.
   - **New "Blending" paragraph** after the settings list: `"blend"` on a placement sets how it mixes with the layers below it:
     - `Additive` for white or same-hue accents;
     - `1 reveals 2` for coloured hits that must keep their colour (additive red over cyan renders white);
     - `Max` for texture over texture;
     - `Layered` fills the dark areas of the layer below.
   - **New "Value curves" paragraph:**
     - A ramp goes in an effect's `E_VALUECURVE_<setting>` key.
     - With `RV=TRUE`, P1, P2, Min and Max are real values in the setting's units, not percentages. Wave speed is ×100 (Max 5000); palette brightness runs 0–400.
     - A brightness ramp inside one effect: `C_VALUECURVE_Brightness=Active=TRUE|Id=ID_VALUECURVE_Brightness|Type=Ramp|Min=0.00|Max=400.00|P1=100.00|P2=300.00|RV=TRUE|` in `settings`.
     - Copy working strings from the user's own sequences when you can.
   - **Palette sentence:** add `music_sparkles: true` for music-reactive sparkles.
   - Add prompt tests pinning "Layer 0 is drawn on top" and the blend/value-curve guidance.
3. **`write_sequence` docstring:**
   - "layer: 0–2 (0 is drawn on top)";
   - the `blend` field;
   - `music_sparkles` in the palette;
   - the layer-cover warning.
4. **README:** extend the `write_sequence` row with "layer 0 draws on top; optional blend mode". Add a line that sequences list only the elements they use and carry the installed xLights version.
5. Commit: "Faces on top; playbook and docs: layer order, blend modes, value curves, music sparkles".

### Task 5: verification

- Full suite and `ruff check` on the changed files: no new findings.
- Re-run the real-show smoke test:

  ```
  .venv/Scripts/python "C:/Users/slick/AppData/Local/Temp/claude/E--/8c935770-b48a-44ae-b6a1-39ac9cf09310/scratchpad/smoke_writer.py"
  ```

  It writes to a scratch copy. Confirm the file has 4 model elements (not 142), the head's `<version>` is `2026.17`, and there are 0 errors.
- Report back; don't push.
