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
