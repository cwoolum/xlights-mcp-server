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

`ModelGroup` gains resolved fields, computed once when the show config loads:

```python
class ModelGroup(BaseModel):
    name: str
    members: list[str]             # direct members as written in the file
    child_groups: list[str]        # direct members that are groups
    parent_groups: list[str]       # groups that list this group as a direct member
    leaf_models: list[str]         # all models reached through nesting (submodels map to their parent model)
    has_submodels: bool            # any direct member is a submodel
    grid_size: str = ""
    layout: str = ""
```

Nesting cycles are broken (a group already on the resolution path is skipped).

### Placeholders

A model is a placeholder when its name contains "Dont Map" (case-insensitive) or its `DisplayAs` is a null/placeholder type. Placeholders are excluded from `leaf_models` counts, from tiers, and from `list_models` unless `include_placeholders=True` (#3).

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

*Candidate* groups are those not already assigned by rules 1–5 and with ≥ 2 leaves. Structure, not size, decides wash: on the Halloween show `Pipes` covers 57% of props by count but has no child groups, while `House` covers 25% with 7 child groups. Model `DisplayAs` can't separate them (108 of 115 props are "Single Line").

**Accent props** are the non-placeholder leaf models of feature groups with ≤ 8 leaves (e.g. `Lantern1`–`Lantern5`, `Spot 1`–`Spot 6`). They're reported per feature group rather than as a separate group tier.

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
    {"name": "Roof Edges", "tier": "feature", "reason": "top-level group, 8 props",
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

Exactly one of `plan` / `plan_path` (a JSON file holding the same list). Each placement:

```json
{"element": "Roof Edges", "layer": 0, "effect": "SingleStrand",
 "start_ms": 12000, "end_ms": 14000,
 "settings": {"E_CHOICE_Chase_Type1": "Left-Right"} ,
 "palette": {"colors": ["#7FE7FF", "#00C8FF"], "brightness": 80, "sparkles": 0}}
```

`settings` may also be xLights' raw `K=V,K=V` string. `palette` is optional (xLights default palette when absent).

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

**Known effect names** = a canonical list of xLights effect names (Off, On, Adjust, Bars, Butterfly, Candle, Circles, Color Wash, Curtain, DMX, Duplicate, Faces, Fan, Fill, Fire, Fireworks, Galaxy, Garlands, Glediator, Guitar, Kaleidoscope, Life, Lightning, Lines, Liquid, Marquee, Meteors, Morph, Moving Head, Music, Piano, Pictures, Pinwheel, Plasma, Ripple, Servo, Shader, Shape, Shimmer, Shockwave, SingleStrand, Sketch, Snowflakes, Snowstorm, Spirals, Spirograph, State, Strobe, Tendril, Text, Tree, Twinkle, Video, VU Meter, Warp, Wave) plus every effect name found in `.xsq` files in the show folder, so names from other xLights versions the user already uses are accepted.

### Timing tracks (#15)

`timing_tracks` may include `"Beats"`, `"Bars"`, `"Drums"`, `"Bass"`, `"Vocals"`:
- **Beats:** one mark per beat of the analysis grid, labelled 1–4 from the (re-anchored) downbeats.
- **Bars:** one mark per downbeat, labelled 1, 2, 3, …
- **Drums / Bass / Vocals:** stem onsets (existing behaviour), only when stems are available; otherwise a warning.

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
3. Call `profile_sequence` on `reference_sequence`, or on the most recently modified hand-made `.xsq` in the show folder when none is given; use its concurrency and layering numbers as targets.
4. Plan section by section: a wash group as base where the section's energy and the reference call for it; rotate which feature groups carry motion; accents on accent props at hits (20–200 ms); energy builds through speed and brightness, not layer count; at most 3 layers; single props only for accents.
5. Call `write_sequence` with `validate_only=true` and the `Beats` (and `Bars`) timing tracks; fix every error; then write.

The prompt body is a Markdown string kept in `src/xlights_mcp/prompts/sequence_song.md` so it can be edited without touching code.

## Baseline `create_sequence`

`create_sequence(mode="auto")` builds a plan and calls the writer's internals, so it inherits every rule:
- **Features:** each section, alternating halves of the feature groups (by `y_range` order) get a background effect on layer 0, chosen from the existing effect tables by the group's majority model category.
- **Accents:** in `drop`/`chorus`/`instrumental` sections, a 100 ms `On` on each downbeat, on layer 1, cycling through accent props.
- **Wash:** in `intro`/`outro`/`breakdown`, the largest wash group gets a `Color Wash` at 40% brightness on layer 0 (features are left dark in those sections).
- **Palette:** `palette_hint` (hex colours or basic colour names, comma-separated) becomes the palette; otherwise the theme palette (#12).
- Timing tracks: Beats and Bars always; stem tracks when available.

Effect names used by the baseline must pass the writer's name check; table entries that map to non-xLights names (e.g. a `Chase` variant) map to `SingleStrand`.

The existing vocal/singing-face path is kept unchanged and runs on its own elements.

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
- **Writer:** one test per rule-table row; timing tracks (Beats labels follow downbeats; Bars numbered; stem track warning without stems); `validate_only` writes nothing; no overwrite without flag; no `.xbkp`.
- **Profile:** concurrency, dark share, parent/child share, overlap count on the fixture.
- **Prompt:** registered, renders with and without `reference_sequence`.
- **Baseline:** on the fixture show plus a synthetic analysis: zero writer errors, no element outside the tiers' groups/accent props, layers ≤ 2 used.

Manual checks (not CI):
- `get_show_layout` on `E:\XLights\HalloweenShow` matches the expected tiers above exactly.
- `profile_sequence` on `Corpse Bride - Remains of the Day.xsq` reproduces the table in *Problem*.
- `create_sequence` on Ghosts 'n' Stuff writes with zero errors, and the file opens in xLights.

All existing tests must still pass.
