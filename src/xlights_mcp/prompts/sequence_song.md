# Sequence {{mp3_path}}

You are sequencing a song for this xLights light show. The server gives you facts about the song and the show, and a writer that checks every plan; the creative decisions are yours. Work through these steps in order and don't skip validation.

## 1. Understand the song

Call `analyze_song` with `mp3_path` = `{{mp3_path}}`. Note:
- the tempo;
- the sections, with label, start and end, and energy;
- whether drums are present in each section;
- whether stems are available (`stems` is not null).

For exact beat and downbeat times, use `get_beat_map`. For hits worth accenting, use `get_stem_events(stem="drums", kind="kicks")`, or `kind="onsets"` for any stem. For dropouts, use `get_stem_events(stem=..., kind="silences")` on any stem; add `merge_gap_ms` to join dropouts split by a stray hit.

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
- **Wash group:** use a wash group only where the section's energy and the reference call for it, such as quiet intros or big drops. Under features, keep it dimmed.
- **Rotation:** rotate which feature groups carry motion between sections and phrases, and don't light everything at once. Match the reference's concurrency and dark share.
- **Accents:** put short accents (20–200 ms) on accent props at hits, for example drum onsets in a drop, or downbeats in a chorus.
- **Energy:** build energy with effect speed, density and brightness, not by stacking layers. Use at most 3 layers (0–2). **Layer 0 is drawn on top**: put accents on layer 0 and bases (wash, Plasma, solid colour) on the highest layer you use. `write_sequence` warns when a base on a top layer completely hides an effect below it.
- **Parents and children:** a group lit at the same time as a group or model inside it reads as one element, and the writer warns about it. Do it on purpose (a dim parent base under a bright child), not by accident.
- **Overlaps:** effects on the same element and layer must not overlap. End one where the next starts.

A placement looks like this:

```json
{"element": "Roof Edges", "layer": 0, "effect": "SingleStrand", "start_ms": 12000, "end_ms": 14000,
 "settings": {"E_NOTEBOOK_SSEFFECT_TYPE": "Chase", "E_CHOICE_Chase_Type1": "Left-Right"},
 "palette": {"colors": ["#7FE7FF", "#00C8FF"], "brightness": 80}}
```

`settings` is optional: xLights uses each effect's defaults for anything you leave out. Some useful settings:
- **SingleStrand chase:** `E_NOTEBOOK_SSEFFECT_TYPE` = `Chase`; `E_CHOICE_Chase_Type1` = `Left-Right`, `Right-Left`, `From Middle` or `Bounce from Left`; `E_TEXTCTRL_Chase_Rotations` sets the number of passes (e.g. `1.0`, `2`, `4`).
- **Color Wash:** `E_TEXTCTRL_ColorWash_Cycles` sets the colour cycles over the effect.
- **Twinkle:** `E_SLIDER_Twinkle_Count` sets the density and `E_SLIDER_Twinkle_Steps` the speed (lower is faster).
- **Shockwave:** `E_SLIDER_Shockwave_Start_Radius` and `E_SLIDER_Shockwave_End_Radius` (0–250).
- **VU Meter synced to a timing track:** `E_CHOICE_VUMeter_Type` = `Timing Event Color` and `E_CHOICE_VUMeter_TimingTrack` = `Beats`.
- **Fades:** `T_TEXTCTRL_Fadein` and `T_TEXTCTRL_Fadeout`, in seconds.

**Blending.** `"blend"` on a placement sets how it mixes with the layers below it (default `Normal`):
- `Additive` for white or same-hue accents;
- `1 reveals 2` for coloured hits that must keep their colour (additive red over cyan renders white);
- `Max` for texture over texture;
- `Layered` fills the dark areas of the layer below.

**Value curves.** A ramp goes in an effect's `E_VALUECURVE_<setting>` key. With `RV=TRUE`, P1, P2, Min and Max are real values in the setting's units, not percentages: Wave speed is ×100 (Max 5000), and palette brightness runs 0–400. A brightness ramp inside one effect goes in `settings` as `C_VALUECURVE_Brightness=Active=TRUE|Id=ID_VALUECURVE_Brightness|Type=Ramp|Min=0.00|Max=400.00|P1=100.00|P2=300.00|RV=TRUE|`. xLights merges effect settings and palette when rendering, so the in-settings ramp works in practice; check the ramp in xLights the first time. Copy working strings only from sequences saved in the current xLights version (`inspect_sequence` shows a sequence's `version`), or check Min and Max against the units above: older files store some values in older units.

`palette` takes 1–8 `#RRGGBB` colours, a `brightness` of 0–400 (default 100), `sparkles` of 0–200, and `music_sparkles: true` (with `sparkles` above 0) for music-reactive sparkles. Without a palette, the effect is white.

For a long plan, write the placements to a JSON file in the show folder and pass `plan_path` instead of `plan`.

## 5. Validate, then write

1. Call `write_sequence` with `mp3_path` = `{{mp3_path}}`, your plan, and `timing_tracks: ["Beats", "Bars"]`. Add `"Kicks"` (and `"Drums"` if you want every drum hit) when stems are available. Set `validate_only: true`.
2. Fix every error it reports and call again until there are none. Read the warnings.
3. Call it once more without `validate_only`. If `<song>.xsq` already exists, pass a new `name`, or `overwrite: true` only if the user agreed to replace it.
4. Report the file path, the effect count, and any warnings you chose to keep.
