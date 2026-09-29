# Brightness Curves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement `docs/superpowers/specs/2026-09-29-brightness-curves-design.md`:
- `palette.brightness` accepts `[t_ms, value]` points, written as xLights' Custom brightness value curve in the palette;
- the playbook gets restart guidance.

**Architecture:**
- A pure conversion helper sits in `xlights/palettes.py`.
- `ColorPalette` gains `brightness_curve`.
- `sequencer/plan.py` validates the points against the placement's framed times and collects snap warnings.

**Tech Stack:** Python 3.12, pydantic v2, pytest.

## Ground rules

- **Branch:** `feat/effect-continuity`, created from `main`.
- **Python:** `.venv/Scripts/python` only; never `uv`.
- **Baseline:** `.venv/Scripts/python -m pytest -q` gives 629 passed, 1 deselected.
- **Commits:**
  - TDD, one commit per task, with `git add <paths>`.
  - End each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Never `-a`, `add .`/`-A`, `stash`, rebase, push or a branch switch.
  - Leave `uv.lock` untracked.
- **Checking the suite before a commit:** read pytest's summary line. Don't pipe pytest into `tail` and chain `&&`, because the pipeline's exit status is `tail`'s.
- **Style:** no comments that restate code; keep CRLF files CRLF; never write into `E:\XLights`.

## Task 1: palette curve model and conversion

**Files:**
- `src/xlights_mcp/xlights/palettes.py`
- `tests/test_palettes.py`

1. Add constants:
   - `CURVE_SLOTS = 200`, the xLights `VC_X_POINTS`;
   - `MAX_BRIGHTNESS = 400`.
2. `ColorPalette` gains `brightness_curve: list[tuple[float, float]] | None = None`: `(x, level)` pairs with `x` from 0 to 1 and `level` from 0 to 400. In `to_xlights_string`:
   - When the curve is set, append `C_VALUECURVE_Brightness=...` (the format below) and don't write `C_SLIDER_Brightness`.
   - Otherwise, behaviour is unchanged.
3. Add `brightness_curve_points(points_ms, start_ms, end_ms) -> tuple[list[tuple[float, float]], list[str]]`. It returns the snapped `(x, level)` pairs plus warning strings, and does the following:
   1. Convert each `(t, v)` to `frac = (t - start) / (end - start)` and `slot = round(frac * 200)`.
   2. A point with the same time as the previous point (a step) gets `slot = previous slot + 1`, capped at 200.
   3. When a later point lands on an occupied slot:
      - it replaces the earlier value;
      - add one warning per placement: "brightness points closer than one curve slot ({slot_ms:.0f} ms) were merged".
   4. If any point moved by more than 25 ms (`|slot/200 × (end - start) - (t - start)| > 25`), add one warning: "brightness curve points snap to {slot_ms:.0f} ms steps on this {len_s:.1f} s effect".
   5. If slot 0 or slot 200 is missing, add it, holding the first or last value.
   6. Return `[(slot / 200, value) for sorted slots]`.
4. The written string format is:

   ```
   C_VALUECURVE_Brightness=Active=TRUE|Id=ID_VALUECURVE_Brightness|Type=Custom|Min=0.00|Max=400.00|RV=TRUE|Values=0.000:0.2500;0.500:0.7500;1.000:0.7500|
   ```

   Write `x` as `f"{x:.3f}"`, which keeps half-slot positions such as 0.005; the Ghosts v2 script used this format and xLights rendered it. Write `y = level / 400` as `f"{y:.4f}"`.
5. Tests:
   - A ramp `[(0, 100), (10000, 300)]` on 0–10000 gives `[(0.0, 100), (1.0, 300)]` with no warnings. The string contains `Values=0.000:0.2500;1.000:0.7500|`, and there's no `C_SLIDER_Brightness`.
   - A step at 5000, `[(0, 100), (5000, 100), (5000, 250), (10000, 250)]`, gives slots 0, 100, 101 and 200.
   - Missing ends are added: `[(2000, 100), (8000, 200)]` on 0–10000 gives slots 0, 40, 160 and 200.
   - A 20 s effect with points 30 ms apart warns about snapping (100 ms steps) and about merging.
   - Serialisation writes slot 1 as `0.005`.
6. Commit with the message "Palette brightness curves (xLights Custom value curve)".

## Task 2: plan validation

**Files:**
- `src/xlights_mcp/sequencer/plan.py`
- `tests/test_plan_validation.py`
- `tests/test_plan_writer.py`

1. In `_palette`, `brightness` may be an int (as now) or a list of `[t_ms, value]` pairs. A list means:
   - each pair is two finite numbers;
   - each value is an int or float from 0 to 400;
   - there are at least 2 pairs.

   `_palette` needs the placement's framed start and end, so pass them in. Frame-round each point time with `to_frame`. Errors:
   - "palette.brightness points must be [t_ms, value] pairs"
   - "palette.brightness needs at least 2 points"
   - "palette.brightness point {t} is outside the placement ({start}-{end} ms)"
   - "palette.brightness point times must not decrease"
   - "palette.brightness values must be 0-400, got {v}"
2. Build the palette with `brightness_curve` set from `brightness_curve_points`. Collect its warnings as `f"placement {i}{_describe(raw)}: {w}"`. The warnings have to flow from `_placement` into `ValidatedPlan.warnings`; extend the return value or pass the warnings list in.
3. `C_VALUECURVE_Brightness` in `settings` (either form) is an error: "put brightness curves in palette.brightness, not settings".
4. Tests:
   - each error above;
   - a valid curve produces a palette with `brightness_curve`;
   - a snap warning shows up in `result.warnings` with the placement prefix;
   - the settings key is rejected;
   - in `test_plan_writer.py`, the written file's `<ColorPalettes>` contains `C_VALUECURVE_Brightness=` and `Type=Custom`.
5. Commit with the message "write_sequence: brightness curves as palette points".

## Task 3: playbook, docstring, README

**Files:**
- `src/xlights_mcp/prompts/sequence_song.md`
- `src/xlights_mcp/server.py` (the `write_sequence` docstring palette line)
- `README.md`
- `tests/test_sequence_song_prompt.py`

1. **Playbook step 4:** add a **Restarts** bullet saying:
   - Every new placement restarts the effect's pattern.
   - Change effects or settings on the beat, ideally on a downbeat or phrase start, where a restart reads as deliberate.
   - Soften changes with `T_TEXTCTRL_Fadein` and `T_TEXTCTRL_Fadeout` (seconds).
   - Never split an effect just to change its brightness; give it a brightness curve.
   - For a smooth speed or colour change on a moving base, put the next effect on the layer above with a fade-in, overlapping the previous one by the fade.
2. **Playbook, value curves:** replace the in-settings brightness-ramp sentence with the palette curve form. Its example is `"brightness": [[64000, 100], [72000, 300]]`, a step is two points at the same time, and the curve has 200 slots, so long effects have coarse steps. Keep the `E_VALUECURVE_` guidance for effect settings.
3. **Playbook, palette line:** `brightness` is 0–400, or `[t_ms, value]` points for a curve.
4. **`write_sequence` docstring palette line:** the same wording.
5. **README `write_sequence` row:** add "brightness curves".
6. Prompt tests: pin the Restarts bullet and the curve example. Remove any assertion on the old in-settings ramp.
7. Commit with the message "Playbook: restart on the beat, fades, brightness curves".

## Task 4: verification

1. The full suite passes, and `ruff check` finds nothing new in the changed files.
2. Write a scratch script at `C:\Users\slick\AppData\Local\Temp\claude\E--\8c935770-b48a-44ae-b6a1-39ac9cf09310\scratchpad\curve_check.py`. It:
   - imports `brightness_curve` from `E:\XLights\HalloweenShow\tools\build_ghosts_v2.py` (read-only; add that `tools` folder's parent to `sys.path`);
   - calls it for `start=0`, `end=16000` ms-equivalent seconds, with pieces `[(0, 4, 100), (4, 8, 180), (8, 16, 260)]`;
   - converts the same steps to points: `[(0, 100), (4000, 100), (4000, 180), (8000, 180), (8000, 260), (16000, 260)]` with times in ms;
   - compares the two `Values` lists slot by slot.

   Every point must match within one slot (0.005) and 0.0025 in `y`. Report any differences.
3. Report back; don't push.
