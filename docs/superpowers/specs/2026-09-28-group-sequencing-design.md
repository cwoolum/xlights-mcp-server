# Group-aware sequencing: show layout, validated plan writer, sequencing playbook

Date: 2026-09-28
Status: Approved design
Covers sharp-edges log items #3, #11, #12, #13, #15, #16, #17, #23 (ranks 1, 4, 5, 10, 11) and part of #24. Section-aware creative choices (#14, #21) move into a playbook prompt instead of server code.

## Problem

- `load_model_groups` looks for `<modelGroup>` inside `<models>`, but xLights stores groups in a separate `<modelGroups>` section. On the Halloween show it returns 0 of 30 groups, so `create_sequence` sequences 128 leaf models, including "Dont Map" placeholders (#11, #3).
- The generator writes overlapping effects into one `<EffectLayer>`, which xLights renders as replace-not-layer (7,168 overlaps in the log, #13), and times that aren't on the 25 ms frame grid (#16).
- The generator's hard-coded creative choices produced an unusable sequence. The version the user liked came from an LLM making creative calls through a hand-written script, because the server had no primitives for it.

Two human-curated sequences show what good looks like (measured 2026-09-28 on `Corpse Bride - Remains of the Day.xsq` and `Into the Unknown.xsq`):

| | Remains of the Day | Into the Unknown |
|---|---|---|
| Elements with effects: groups / models | 19 / 15 | 14 / 6 |
| Overlaps within a layer | 0 | 0 |
| Elements lit at once (median / p90) | 5 / 13 | 2 / 6 |
| Song fully dark | 2% | 4% |
| Parent lit while a child group is also lit | House 51%, All 39%, Roof 0%, Spots 0% | All 50%, House 21%, others 0% |

Groups carry most effects; elements take turns; parents act as a base under child features; single props are used for accents. The style differs a lot between songs, so choreography is a judgment call per song.

## Decision: server provides facts and invariants, a playbook provides taste

- **MCP server:** deterministic show facts (layout, tiers, style profiles) and a writer that enforces xLights' structural rules for any plan, whoever wrote it.
- **Playbook:** an MCP prompt (`sequence_song`) that guides a model through analysing the song, reading the layout, learning from a reference sequence, planning, and writing. MCP prompts work in every MCP client (Claude, Copilot, Cursor, VS Code); it can later be mirrored as a Claude skill.
- **`create_sequence` auto mode** stays as a simple baseline that builds a plan and goes through the same writer.

## Show layout

### Group parsing

`load_model_groups(show_path)` reads `<modelGroups>/<modelGroup>` and falls back to `<modelGroup>` inside `<models>` (older files). Each group's `models` attribute lists direct members, which may be models, other groups, or submodels (`Model/Sub`).

`ModelGroup` gains resolved fields, computed once when the show config loads. All new fields have defaults so existing `ModelGroup(name=..., members=...)` callers (remapper tests) keep working:

```python
class ModelGroup(BaseModel):
    name: str
    members: list[str] = []          # direct members as written in the file
    child_groups: list[str] = []     # direct members that are groups
    parent_groups: list[str] = []    # groups that list this group as a direct member
    leaf_models: list[str] = []      # all non-placeholder models reached through nesting (submodels map to their parent model)
    has_submodels: bool = False      # any direct member is a submodel
    grid_size: str = ""
    layout: str = ""
```

Nesting cycles are broken (a group already on the resolution path is skipped). If a group name is defined more than once (the Halloween file defines `Trees` twice), the first definition wins and `get_show_layout` reports a warning.

Behaviour change: `remap_sequence` receives the show's groups too (it received none before, because of the parsing bug). The remapper tests must still pass; any remap behaviour change is reported in the PR.

### Placeholders

A model is a placeholder when its name matches `d(on'?t|o not) map` (case-insensitive) — this covers `Dont Map`, `Don't Map` and `Do Not Map` (all six Halloween placeholders are `DisplayAs="Single Line"`, so display type can't identify them). Placeholders are excluded from `leaf_models`, from tiers, from `ungrouped_models`, and from `list_models` unless `include_placeholders=True` (#3).

### Tiers

Each group gets a suggested tier and a one-line reason. Rules, first match wins:

| # | Condition | Tier |
|---|---|---|
| 1 | Override file names the group | that tier |
| 2 | No non-placeholder leaf models (empty) | `skip` |
| 3 | Name contains "preview" (case-insensitive) | `skip` |
| 4 | `has_submodels` (row/segment groups like `Peace-P1`) | `skip` |
| 5 | ≥ 2 direct child groups that each have ≥ 2 leaves, or leaves cover ≥ 80% of the display | `wash` |
| 6 | Fewer than 2 leaves | `skip` (single prop; still usable by name) |
| 7 | Leaf set is a strict subset of another *candidate* group's leaf set | `skip` (a sub-part of a feature; still usable by name) |
| 8 | Otherwise | `feature` |

*Candidate* groups are those not already assigned by rules 1–5 and with ≥ 2 leaves. Structure, not size, decides wash: on the Halloween show `Pipes` covers 57% of props by count but has no child groups, while `House` covers 25% with 7 child groups. Model `DisplayAs` can't separate them (114 of the file's 128 models are "Single Line").

**Accent props** are the non-placeholder leaf models of feature groups with ≤ 8 leaves. They're reported per feature group rather than as a separate group tier. On Halloween that's 9 groups / 43 props — lanterns and spots, but also individual roof tiers, door and window lines, which matches the human sequences (Remains of the Day lights individual lanterns and roof tiers for accents).

A "display" here is the set of all non-placeholder models. Tiers are suggestions: every group and model stays usable by name in a plan.

Expected on the Halloween show (simulated against its `xlights_rgbeffects.xml` on 2026-09-28):
- **wash:** `All`, `House`, `Roof`
- **feature:** `Roof Edges`, `Tier 3`, `Tier 1-2 Mid`, `Door`, `Entry Post`, `Under Window`, `Walkway`, `Pipes`, `Spots`, `Lanterns`, `Spooky Fence`
- **skip:** `Peace-P1`…`Peace-P7` (submodels), `Peace-Odd`, `Peace-Even` (part of Pipes), `Under Roof`, `Top Roof` (part of Roof Edges), `Tree Spots` (part of Spots), `Trees`, `Lantern Center` (empty), `PreviewONLY All` (preview), `Pathlights` (single prop)

### Override file

Optional `xlights-mcp.json` in the show folder:

```json
{"tiers": {"Peace-Odd": "feature", "Tree Spots": "skip"}}
```

Unknown group names in the file produce a warning in `get_show_layout`, not an error. Invalid tier values are ignored with a warning.

### `get_show_layout(show_name: str | None = None)`

Returns, for the active (or named) show:

```json
{
  "show": "halloween",
  "model_count": 123, "placeholder_count": 5,
  "groups": [
    {"name": "Roof Edges", "tier": "feature", "reason": "top-level, 9 props",
     "child_groups": ["Under Roof"], "parent_groups": ["House", "All"],
     "prop_count": 9, "y_range": [102, 179], "accent_props": []}
  ],
  "ungrouped_models": ["Tree 6ft"],
  "warnings": []
}
```

`y_range` comes from member models' `WorldPosY` (height). Groups are listed wash → feature → skip, then by name.

## Plan writer: `write_sequence`

```
write_sequence(mp3_path: str, plan: list[dict] | None = None, plan_path: str | None = None,
               name: str | None = None, timing_tracks: list[str] | None = None,
               overwrite: bool = False, validate_only: bool = False) -> dict
```

Exactly one of `plan` / `plan_path` (a JSON file holding the same list; relative paths resolve against the active show folder).

**Song facts:** the tool is `async` and gets the song's duration, beat grid, downbeats and stems from `full_analysis` through the same `_analyze_in_thread` helper the analysis tools use (per-file lock, progress notifications). A cached song returns instantly; an unanalysed song runs the full pipeline first, like `get_beat_map` does.

Each placement:

```json
{"element": "Roof Edges", "layer": 0, "effect": "SingleStrand",
 "start_ms": 12000, "end_ms": 14000,
 "settings": {"E_CHOICE_Chase_Type1": "Left-Right"} ,
 "palette": {"colors": ["#7FE7FF", "#00C8FF"], "brightness": 80, "sparkles": 0}}
```

`settings` is either a `{key: value}` map (preferred; a value containing `,` is an error because xLights separates settings with commas) or xLights' raw `K=V,K=V` string, which is written verbatim after checking every comma-separated part contains `=`.

**Palette mapping.** `ColorPalette` gains `brightness: int = 100`. A plan palette maps as:
- `colors`: 1–8 colours in `#RRGGBB` form. Colour *n* fills palette slot *n* and is checked (`C_CHECKBOX_Palette{n}=1`); unused slots keep xLights' default colours, unchecked.
- `brightness` (0–400, default 100) → `C_SLIDER_Brightness`, omitted when 100.
- `sparkles` (0–200, default 0) → `C_SLIDER_SparkleFrequency`, omitted when 0.
- No `palette` → a palette with slot 1 = `#FFFFFF` checked, written explicitly (every effect in the human sequences carries a palette).

The writer collects palettes from the placements themselves (deduplicated by their serialised string); the current `write_xsq` behaviour of silently dropping a palette that isn't pre-registered in `SequenceSpec.palettes` is removed.

**Layer positions.** In xLights a layer's number is its position among the element's `<EffectLayer>`s. The writer emits empty `<EffectLayer/>`s for unused lower layers, so a placement on layer 2 stays on layer 2 (today `write_xsq` emits only used layers, silently renumbering them).

### Rules

Hard errors abort the write; auto-fixes are applied and counted.

| Check | Behaviour |
|---|---|
| Times not on the sequence's frame grid (25 ms) | auto-fix: round to nearest frame |
| Effect extends past the song end | auto-fix: clip to duration |
| `end_ms <= start_ms` after rounding/clipping | error |
| Overlap on the same element and layer (touching end == start is fine) | error naming both placements (index, element, layer, times) |
| `layer` outside 0–2 | error |
| `element` not a model or group in the show | error with up to 3 close-name suggestions (difflib) |
| `element` is a submodel (`Model/Sub`) | error: submodel elements aren't supported yet; use a group |
| `effect` not a known xLights effect name | error with close-name suggestions |
| Malformed `settings` string or palette colour | error |
| Parent group and a group/model it contains both have effects at the same moment | warning (counted, first 10 listed) |

**Known effect names** live in `xlights/effects.py` as `XLIGHTS_EFFECT_NAMES`: a canonical list of xLights effect names (Off, On, Adjust, Bars, Butterfly, Candle, Circles, Color Wash, Curtain, DMX, Duplicate, Faces, Fan, Fill, Fire, Fireworks, Galaxy, Garlands, Glediator, Guitar, Kaleidoscope, Life, Lightning, Lines, Liquid, Marquee, Meteors, Morph, Moving Head, Music, Piano, Pictures, Pinwheel, Plasma, Ripple, Servo, Shader, Shape, Shimmer, Shockwave, SingleStrand, Sketch, Snowflakes, Snowstorm, Spirals, Spirograph, State, Strobe, Tendril, Text, Tree, Twinkle, Video, VU Meter, Warp, Wave) plus every effect name found in `.xsq` files in the show folder, so names from other xLights versions the user already uses are accepted. The effect library behind `list_effects` is reconciled with this list: its `Chase` entry (not a real xLights effect) becomes `SingleStrand`, and every name it advertises must pass the writer's check (tested).

### Timing tracks (#15)

`timing_tracks` may include `"Beats"`, `"Bars"`, `"Drums"`, `"Bass"`, `"Instruments"`:
- **Beats:** one mark per beat of the analysis grid. The label is the beat's position in its bar: 1 on each downbeat, counting up until the next downbeat. Bars are normally 4 beats; a partial bar before a re-anchored drop has fewer. Beats before the first downbeat count backwards so the beat just before it is `4` (e.g. `3, 4, 1, 2, …`).
- **Bars:** one mark per downbeat, labelled 1, 2, 3, …
- **Drums / Bass / Instruments:** stem onsets, as the engine writes today (Instruments = the `other` stem), only when stems are available; otherwise a warning and the track is omitted.

`Vocals` isn't a stem track name: the lyric/singing-face path already writes a timing track called `Vocals`. Timing track names must be unique within a sequence; a duplicate is an error.

Internally the writer also accepts pre-built `TimingTrack` objects (multi-layer lyric tracks: words, words, phonemes) alongside the named tracks, for the singing-face path.

All marks are frame-rounded; each mark ends where the next starts (last ends at song end). Plans can reference them in VU Meter settings (`E_CHOICE_VUMeter_TimingTrack=Beats`).

### Output

- File: `<name or mp3 stem>.xsq` in the active show folder. If it exists and `overwrite` is false: error. Never writes `.xbkp` (#23).
- `validate_only=True` runs every check and returns the report without writing.
- Report:

```json
{"path": "E:/XLights/HalloweenShow/Ghosts n Stuff.xsq", "written": true,
 "elements": 9, "effects": 412, "max_layer": 2,
 "adjusted": {"rounded_to_frame": 37, "clipped_to_end": 1},
 "errors": [], "warnings": ["2 moments where House and Roof Edges are both lit"]}
```

## Style profile: `profile_sequence(xsq_path: str)`

Reads an `.xsq` against the active show's layout and returns:
- duration; elements with effects split into groups / models; total effects
- per element: layers used, effect count, median effect length, share of the song lit, top effect names
- elements lit at once (median, p90, max) and share of the song fully dark (sampled every 50 ms; `Off` effects don't count as lit)
- per parent group: share of its lit time during which a contained element is also lit
- overlaps within a layer (a count; human sequences are 0)

Output is compact (per-element rows capped at the 20 busiest, remainder summarised). Relative paths resolve against the active show folder.

## Playbook prompt: `sequence_song`

`@mcp.prompt()` with arguments `mp3_path` and optional `reference_sequence`. The returned message instructs the model to:

1. Call `analyze_song`; read sections, tempo, drum presence.
2. Call `get_show_layout`; read tiers and accent props. If the show folder has `.claude/CLAUDE.md`, read it and follow it.
3. Call `profile_sequence` on `reference_sequence`, or on the most recently modified hand-made `.xsq` in the show folder when none is given; use its concurrency and layering numbers as targets. A sequence is hand-made when its `<head><comment>` isn't the MCP generator's (`Generated by xLights MCP Server`); `list_sequences` gains a `generated: bool` per entry so the model can tell.
4. Plan section by section: a wash group as base where the section's energy and the reference call for it; rotate which feature groups carry motion; accents on accent props at hits (20–200 ms); energy builds through speed and brightness, not layer count; at most 3 layers; single props only for accents.
5. Call `write_sequence` with `validate_only=true` and the `Beats` (and `Bars`) timing tracks; fix every error; then write.

The prompt body is a Markdown string kept in `src/xlights_mcp/prompts/sequence_song.md` so it can be edited without touching code.

## Baseline `create_sequence`

`create_sequence(mode="auto")` builds a plan and calls the writer's internals, so it inherits every rule:
- **Features:** each section, alternating halves of the feature groups (by `y_range` order) get a background effect on layer 0, chosen from the existing effect tables by the group's majority model category.
- **Accents:** in `drop`/`chorus`/`instrumental` sections, a 100 ms `On` on each downbeat, on layer 1, cycling through accent props.
- **Wash:** in `intro`/`outro`/`breakdown`, the largest wash group gets a `Color Wash` at 40% brightness on layer 0 (features are left dark in those sections).
- **Palette:** `palette_hint` becomes the palette; otherwise the theme palette (#12). It accepts hex colours and these names, separated by commas and/or "and": red, green, blue, white, warm white, yellow, orange, gold, purple, pink, magenta, cyan, ice. An unrecognised word is reported in the result and ignored; if nothing is recognised, the theme palette is used. The tool docstring is updated to match.
- Timing tracks: Beats and Bars always; Drums/Bass/Instruments when stems are available.
- **File naming:** unchanged — never overwrites; picks `<song> (generated N).xsq`. (`write_sequence` instead errors unless `overwrite=true`, because an LLM-authored plan usually targets a chosen name.)
- `SECTION_TYPE_CONFIG` stays in `engine.py` (tests import it).

Effect names used by the baseline must pass the writer's name check; table entries that map to non-xLights names (e.g. a `Chase` variant) map to `SingleStrand`.

**Singing faces** (models with face definitions):
- The `needs_vocal_assignment` early return stays and happens before anything is written.
- When lyrics are available, the face effects and lyric timing tracks are built as today and passed to the writer as extra placements and pre-built `TimingTrack`s.
- When lyrics are unavailable, singing models get no effects (the old table-engine fallback for them is removed) and the result carries a warning.
- Wash/feature groups whose leaf models include a singing model are left out of the baseline when faces are being sequenced, so group effects don't draw over the faces.

Everything else in the old `_generate_auto` (per-model effect loops, legacy prefix grouping) is removed.

## Delivery

One design, three PRs in order, each leaving the server working:
1. **Layout:** group parsing, placeholders, tiers, override file, `get_show_layout`, `list_models` change.
2. **Writer:** `write_sequence`, validation, palette/layer/timing-track output, effect-name list reconciliation.
3. **Authoring:** `profile_sequence`, `sequence_song` prompt, `list_sequences.generated`, baseline `create_sequence` rewrite.

## Other changes

- `list_models(include_placeholders=False)` hides placeholders (#3).
- `inspect_sequence`, `preview_plan`, `get_energy_profile`, `get_beat_map` sizing (#5–#7, #10) are out of scope (PR C).

## Testing

Unit tests use fixture files in `tests/fixtures/show_groups/`:
- `xlights_rgbeffects.xml` with: models incl. a "Dont Map" placeholder; groups in `<modelGroups>` with nesting (`House` ⊃ `Roof Edges` ⊃ `Under Roof`), an `All` group, a submodel-row group, an empty group, a preview group, two small accent groups; one group placed inside `<models>` (legacy location).
- A small human-style `.xsq` for `profile_sequence`.

Tests:
- **Parsing:** both group locations; nested resolution; cycle safety; placeholders excluded.
- **Tiers:** each rule row, including a large childless group (Pipes-like) staying `feature` and a group with exactly 2 child groups becoming `wash`; override file (valid, unknown group, invalid tier).
- **Writer:** one test per rule-table row; layer positions preserved (a layer-2-only element emits two empty layers first); palette mapping (slots, brightness, sparkles, default palette; palettes collected from placements); timing tracks (Beats labels restart at downbeats incl. partial bars and pickup beats; Bars numbered; stem track warning without stems; duplicate track name error); `validate_only` writes nothing; no overwrite without flag; no `.xbkp`.
- **Effect names:** every name `list_effects` advertises passes the writer's check.
- **Remapper:** existing remap tests still pass with groups now parsed.
- **Profile:** concurrency, dark share, parent/child share, overlap count on the fixture.
- **Prompt:** registered, renders with and without `reference_sequence`.
- **Baseline:** on the fixture show plus a synthetic analysis: zero writer errors, no element outside the tiers' groups/accent props, layers ≤ 2 used.

Manual checks (not CI):
- `get_show_layout` on `E:\XLights\HalloweenShow` matches the expected tiers above exactly.
- `profile_sequence` on `Corpse Bride - Remains of the Day.xsq` reproduces the table in *Problem*.
- `create_sequence` on Ghosts 'n' Stuff writes with zero errors, and the file opens in xLights.

All existing tests must still pass.
