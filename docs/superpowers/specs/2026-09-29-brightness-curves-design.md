# Brightness curves and restart guidance

Date: 2026-09-29
Status: Approved design (a slimmed-down rank 1 from `E:\XLights\mcp-sharp-edges.md`)

## Problem

Every new placement restarts its effect's pattern: xLights' clock for effects like Plasma, Galaxy, Wave and chases is "frames since this effect started". The Ghosts v2 plan split continuous bases to step their brightness, which caused visible resets at non-musical moments. `write_sequence` has no way to change brightness inside one effect, so the script smuggled a `C_VALUECURVE_Brightness` string in through `settings`.

## What hand-made sequences do

Measured on the user's 38 hand-made song sequences, 2026-09-29:
- **Brightness value curves are rare:** 4 songs, 15 effects.
- **Layer crossfades are rare:** 8 songs, 18 instances.
- **Fades are common:** about 40% of effects have `T_TEXTCTRL_Fadein` or `T_TEXTCTRL_Fadeout`.
- **Back-to-back restarts of the same moving effect are common:** 30 songs, 1,300 or more instances. Restarts are on the beat far more often than chance, but not specifically on downbeats:

  | Sequence | On a beat | On a downbeat | Downbeat by chance |
  |---|---|---|---|
  | Remains of the Day | 93% | 18% | 7% |
  | Superstition | 83% | 83% | 4% |
  | Carnival | 45% | 14% | 5% |
  | Beetlejuice (orchestral, free time) | 0% | 0% | 6% |

  Restarts on the beat read as deliberate.

So there's no `crossfade_ms` feature. It's the rare case, and the playbook can describe the manual pattern. A value-curve helper for effect settings is deferred to rank 4, which builds the per-setting ranges table.

## Brightness curve

**Plan shape:** `palette.brightness` takes a number, as today, or a list of `[t_ms, value]` points.
- Values are 0–400.
- Times are song times within the placement, `start_ms <= t <= end_ms`, and must not decrease. They're frame-rounded like other times.
- There must be at least 2 points.
- Brightness is linear between points. Two points at the same time make a step.
- Before the first point the curve holds the first value; after the last point it holds the last.

**Model:** `ColorPalette` gains `brightness_curve: list[tuple[float, float]] | None`: `(x, level)` pairs with `x` from 0 to 1 across the effect and `level` from 0 to 400. When the curve is set, `brightness` is ignored.

**Output:** the curve goes in the palette string, which is where xLights keeps it:

```
C_VALUECURVE_Brightness=Active=TRUE|Id=ID_VALUECURVE_Brightness|Type=Custom|Min=0.00|Max=400.00|RV=TRUE|Values=x:y;…|
```

- `x` has 3 decimal places, so half-slots like 0.005 survive; this is the format the Ghosts v2 script used. `y = level / 400` has 4 decimal places.
- Points snap to 200 slots across the effect (xLights' `VC_X_POINTS`), so `x = round(frac × 200) / 200`.
- A step's second point goes one slot later; a step at the very end uses slots 199 and 200.
- Slots never go backwards: a point that would land before the previous one takes its slot.
- Slots round half up.
- If the curve doesn't start at `x = 0` or end at `x = 1`, points are added there holding the first and last values.
- Two points that land on the same slot keep the later one.

**Warnings:**
- Snapping moves a point more than 25 ms. This happens when the effect is longer than 10 s (the largest move is half a slot), and the warning gives the effect's resolution in ms. It's listed once per placement.
- Two points collapsed into one slot.

**Errors:**
- a point outside the placement's frame-rounded times (before clipping to the song end);
- times out of order;
- a value outside 0–400;
- fewer than 2 points;
- `C_VALUECURVE_Brightness` in `settings`: use the palette curve instead.

**Layer-cover warning:** it ignores brightness, exactly as today.

## Playbook, docstring, README

**Playbook (`sequence_song.md`), step 4:**
- Every new placement restarts the effect's pattern. Change effects or settings on the beat, ideally on a downbeat or phrase start, where a restart reads as deliberate.
- Soften changes with `T_TEXTCTRL_Fadein` and `T_TEXTCTRL_Fadeout` (seconds).
- Never split an effect just to change its brightness. Give it a brightness curve (`"brightness": [[t_ms, value], ...]`) instead.
- For a smooth change of speed or colour on a moving base, put the next effect on the layer above with a fade-in, overlapping the previous one by the fade. This replaces the old sentence about the in-settings brightness ramp.

**`write_sequence` docstring:** the palette line mentions the curve form.

**README:** the `write_sequence` row mentions brightness curves.

## Testing

**Unit tests:**
- **Conversion:**
  - a two-point ramp gives `0.000:y0;1.000:y1`;
  - a mid-effect step goes one slot later;
  - start and end points are added when missing;
  - the snap warning appears on a 20 s effect with closely spaced points;
  - two points in one slot collapse, with a warning.
- **Errors:**
  - a point outside the placement;
  - times out of order;
  - a value above 400;
  - a single point;
  - a curve given in `settings`.
- **Palette string:** the curve is written and `C_SLIDER_Brightness` is not.

**Writer round trip:** the curve appears in `<ColorPalettes>` of the written file.

**Real check:** re-express one Ghosts v2 House stretch as a points curve. Its snapped `Values` must match what `build_ghosts_v2.brightness_curve` produced for the same pieces, within one slot.
