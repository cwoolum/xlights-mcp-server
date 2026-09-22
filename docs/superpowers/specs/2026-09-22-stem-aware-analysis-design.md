# Stem-aware analysis: honest structure, drum-locked beat grid, stem events tool

Date: 2026-09-22
Status: Approved design
Covers sharp-edges log items #4, #8, #18, #19, #20 (ranks 2–3). Item #9 (expose the cache path) is dropped: the new tool makes the cache an implementation detail.

## Problem

Stem separation already runs and its results (per-stem onsets and energy) sit in the analysis cache, but:

- No tool returns them (#8).
- Beats and structure run *before* stems, so neither can use them. The librosa grid lags the drums by ~45 ms and has the wrong downbeat phase after the breakdown (#19).
- Every section of an EDM track comes back `chorus` at 0.65, and boundaries miss both drops by a bar (#4, #18). On *Ghosts 'n' Stuff* the drum stem alone locates intro, riser, drop, breakdown and outro (#20).

Reference track for all numbers below: `E:\XLights\HalloweenShow\Music\GhostsnStuffft.RobSwire.mp3` (187.3 s, ~129 BPM). Ground truth from the drum stem: first kick of drop 1 at 66.873 s, drums stop at 110.086 s (hi-hat decays ~3 s), first kick of drop 2 at 140.388 s.

## Goals

1. Beat grid locked to the drum stem when stems exist; bar 1 lands on each drop.
2. Section labels derived from drum presence, with an EDM vocabulary, for tracks that have at least one structural drum gap (defined below). Tracks without one keep the current labeller.
3. Per-stem data reachable through a tool, sized for an LLM.
4. Everything degrades to today's behaviour when stems are unavailable, and says so.

Non-goals: new `create_sequence` behaviour for the new labels (PR B), `get_beat_map` / `get_energy_profile` size fixes (PR C, #6 #7).

## Pipeline

`full_analysis` order becomes:

1. spectrum
2. stems — separate, then `analyze_stems` (now also computes `silences`)
3. beats — receives the drum `StemOnsets`, or `None`
4. structure — receives the drum `StemOnsets` and the beat map, or `None`

Progress still reports 5 stages, in the new order. If separation or stem analysis fails, stages 3–4 receive `None` and behave exactly as today.

## Data model changes

`StemOnsets` (audio/analyzer.py) gains:

```python
silences: list[tuple[float, float]]  # seconds, [start, end)
```

A silence is a span where the stem's normalised RMS stays below `SILENCE_THRESHOLD = 0.05` for at least `MIN_SILENCE_S = 1.0`. Computed once in `analyze_stems` for every stem.

`BeatMap` (audio/beats.py) gains:

```python
beat_source: Literal["madmom", "librosa"] = "librosa"
drum_aligned: bool = False
```

`SongSection` (audio/structure.py):

```python
label: str  # intro | build | drop | breakdown | outro | verse | chorus | bridge | transition | instrumental
structure_source: Literal["stems", "mixdown"] = "mixdown"
drums: Literal["present", "absent", "decaying"] | None = None  # None when structure_source == "mixdown"
```

`cache.ANALYSIS_VERSION` goes from 1 to 2. Old JSON entries are ignored; stem WAVs on disk are reused, so re-analysis costs ~10 s, not ~50 s.

## Drum runs and gaps (shared definitions)

One new module, `audio/drums.py`, owns these definitions. `beats.py` and `structure.py` both call it; neither re-derives them.

```python
def drum_runs(drums: StemOnsets, beat_period: float) -> list[DrumRun]
def drum_gaps(runs: list[DrumRun], duration: float) -> list[DrumGap]
```

- **Raw run**: a maximal stretch between two consecutive drum `silences` (or track start/end) that contains at least one drum onset. `start` = first onset in it, `end` = last onset in it.
- **Run** (the only kind anything else uses): a raw run whose `end - start ≥ 4 * beat_period` (at least one bar). Shorter raw runs — an isolated crash or tom hit — are discarded and their time is treated as part of the surrounding gap.
- **Gap**: the interval between one run's `end` and the next run's `start`, plus the leading gap `[0, first run start)` and the trailing gap `(last run end, duration]`. Gap length is measured on this interval (last onset to next first onset), in seconds and in bars (`length / (4 * beat_period)`).
- **Structural gap**: a gap of ≥ 4 s. Gaps shorter than 4 s (a one-bar drum stop) are not structural: they create no section boundary and no re-anchoring; drums count as present through them.
- **Decaying**: a structural gap is `decaying` when more than 1 s separates the preceding run's last onset from the start of the drum silence span that follows it (the stem tails off rather than cutting). Otherwise `absent`.
- **Anchor run**: a run that is preceded by a structural gap (including a leading gap ≥ 4 s).

```python
class DrumRun(BaseModel):
    start: float  # first onset, seconds
    end: float    # last onset, seconds

class DrumGap(BaseModel):
    start: float
    end: float
    bars: float
    kind: Literal["leading", "mid", "trailing"]
    structural: bool   # length >= 4 s
    decaying: bool
```

`beat_period` is always `60 / tempo` of the **base grid** (step 1 below), which `BeatMap.tempo` keeps; it is not recomputed after snapping. `beats.py` and `structure.py` therefore compute identical runs.

`StemOnsets` moves from `analyzer.py` into a dependency-free `audio/stems_model.py` (re-exported from `analyzer.py` for existing imports), so `drums.py` → `stems_model.py` and `beats.py` → `drums.py` introduce no import cycle.

## Beat grid

In `detect_beats(audio_path, sr, drums: StemOnsets | None = None)`:

1. **Base grid.** madmom `RNNDownBeatProcessor` + `DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)` if madmom imports; otherwise librosa `beat_track`. `beat_source` records which ran. Tempo = 60 / median inter-beat interval. Base downbeats: madmom's bar-position-1 beats, or every 4th beat from the first beat for librosa (today's behaviour).
2. **Snap** (only when `drums` given). Each beat moves to the nearest drum onset within ±60 ms. Beats with no drum onset in range keep their position.
3. **Re-anchor downbeats** (only when at least one anchor run exists). For each anchor run, the snapped beat nearest its `start` becomes a downbeat; every 4th beat after it is a downbeat until the next anchor. Beats before the first anchor are counted backwards from it in steps of 4. Where the count from one anchor meets the next anchor mid-bar, the shorter partial bar before the new anchor is intended (drops are placed against the phrase, not the previous bar count). An anchor more than half a beat period from its nearest beat (the grid doesn't reach that far, e.g. librosa trimmed edge beats) is dropped; if no anchor remains, step 4 applies.
4. When no anchor run exists (steady drums, or no drum onsets), downbeats stay as in step 1. Snapping still applies.
5. `drum_aligned = True` when step 2 ran, i.e. `drums` was given and has at least one onset.
6. `onset_times` stays the mixdown onsets. Per-stem onsets are served by `get_stem_events`.

Measured on the reference track: madmom beats land within +7 / −16 / +22 ms of the three drum events but its downbeats are 438–467 ms off at both drops, which is why step 3 overrides bar phase at anchors regardless of source.

## Structure

`detect_structure(audio_path, sr, drums: StemOnsets | None = None, beats: BeatMap | None = None)`.

### Mode selection

| Condition | Mode | `structure_source` |
|---|---|---|
| `drums` is `None` | today's algorithm | `mixdown`, `drums = None` |
| drum stem present, and at least one structural gap lies strictly between two runs | EDM labelling (below) | `stems` |
| otherwise (no runs, steady drums, only leading/trailing silence, or only short stops) | today's labeller for boundaries and labels; per section, `drums = "present"` if runs cover more than half of it, else `"absent"` | `stems` |

So a pop song with a drumless intro or a one-bar drum stop keeps pop labels; a track whose drums drop out for ≥ 4 s mid-song gets EDM labels. Known consequence, accepted: a pop song with a drumless bridge of ≥ 4 s is labelled EDM-style (choruses as `drop`, the bridge as `breakdown`).

### EDM labelling

1. **Boundaries.** Candidates are every run start and run end adjacent to a structural gap, plus the existing novelty/energy boundaries. A novelty boundary within 2 s of a drum boundary is dropped in favour of the drum boundary. Every boundary snaps to the nearest downbeat within half a bar; a boundary with no downbeat that close (the grid has a hole) keeps its raw time. A section shorter than 3.5 beats (a partial bar; snapped downbeat spacing jitters around one bar) merges into its predecessor; if it is the first section, into its successor. Anchor boundaries (drop starts) are never removed: a short section starting at an anchor merges forward instead, and is left short if its end is also an anchor or the track end.
2. **Labels.** Each section gets exactly one label, by the first matching row:

   | # | Section | Label | `drums` |
   |---|---|---|---|
   | 1 | Inside the leading structural gap | `intro` | `absent` |
   | 2 | Inside the trailing structural gap | `outro` | `absent` or `decaying` |
   | 3 | Inside a mid-song structural gap of ≤ 8 bars | `build` | `absent` or `decaying` |
   | 4 | Inside a mid-song structural gap of > 8 bars, before or with no novelty boundary inside the gap | `breakdown` | `absent` or `decaying` |
   | 5 | Inside a mid-song structural gap of > 8 bars, after the **last** novelty boundary inside the gap | `build` | `absent` |
   | 6 | Starts at an anchor run's start | `drop` | `present` |
   | 7 | First section of the track, drums present (no leading structural gap) | `intro` | `present` |
   | 8 | Any other drums-present section | label of the most recent drums-present section (never a gap label); `drop` if there is none | `present` |

   `decaying` for rows 2–4 comes from the gap's decaying flag (see *Drum runs and gaps*); it applies only to the first section of that gap. Section boundaries at a run end are placed at the run's last onset (snapped), not at the silence start.
3. **Confidence**: 0.9 for EDM labels. The fallback labeller keeps its own confidences (0.4–0.7), unchanged.

Expected on the reference track: drums play from the start (row 7 `intro`, then row 8 continues it), a ~10 s gap (≈ 5 bars) → `build`, drop 1 at the downbeat nearest 66.873 s, row 8 continues `drop`, breakdown from the downbeat nearest 110.086 s (≈ 16-bar gap, `decaying`), a trailing `build` if novelty marks the riser, drop 2 at the downbeat nearest 140.388 s, then `outro` if the drums stop ≥ 4 s before the end.

### Engine compatibility

`SECTION_TYPE_CONFIG` in sequencer/engine.py gains three aliases so no new label falls through to `unknown`: `build` → `transition` config, `drop` → `chorus` config, `breakdown` → `bridge` config. `create_sequence` output will change where labels, boundaries and downbeats change; no new generation behaviour is added.

## Tool surface

### `analyze_song` response additions

```json
"beat_source": "madmom",
"drum_aligned": true,
"structure_source": "stems",
"stems": {
  "drums":  {"onsets": 533, "mean_energy": 0.41, "silences_ms": [[57120, 66850], [113200, 140360]]},
  "bass":   {"onsets": 156, "mean_energy": 0.33, "silences_ms": [...]},
  "vocals": {"onsets": 415, "mean_energy": 0.22, "silences_ms": [...]},
  "other":  {"onsets": 190, "mean_energy": 0.37, "silences_ms": [...]}
}
```

(Numbers illustrative. The drum silence after the breakdown starts ~3 s after the last onset at 110.086 s because the hi-hat decays, which is what makes that gap `decaying`.)

`stems` is `null` when stems are unavailable. Each section entry gains `drums`. All times in this block are integer milliseconds. No file paths are returned.

### New tool: `get_stem_events`

```
get_stem_events(mp3_path: str, stem: str, kind: str,
                start_ms: int | None = None, end_ms: int | None = None,
                max_events: int = 500, resolution: str = "beat") -> dict
```

- `stem` ∈ `drums | bass | vocals | other`; `kind` ∈ `onsets | energy | silences`; `resolution` ∈ `beat | bar` (used only by `energy`). Invalid values return `{"error": ...}` listing the valid ones.  `max_events` must be ≥ 1 and `start_ms` ≤ `end_ms`; otherwise an error. Windowing and `next_start_ms` use integer milliseconds so paging never skips an item.
- Window `[start_ms, end_ms)` defaults to the whole track.
- `onsets` → `{"stem", "kind", "count", "events_ms": [int, ...]}`.
- `energy` → `{"stem", "kind", "resolution", "points": [{"t_ms": int, "energy": float (3 dp)}]}`. `beat`: one mean value per beat span `[beat_i, beat_{i+1})` of the re-phased grid; `bar`: one per `[downbeat_i, downbeat_{i+1})`. The last span ends at track end; if the grid starts after 0, a leading span [0, first grid point) is included (so intros are visible); an empty grid gives one span [0, duration). A span is included when its start is in the window.
- `silences` → `{"stem", "kind", "spans_ms": [[start, end], ...]}`, clipped to the window.
- Truncation (`onsets` events and `energy` points): if more than `max_events` fall in the window, return the first `max_events`, plus `"truncated": true` and `"next_start_ms"` (time of the first omitted item).
- Served from the analysis cache; runs `full_analysis` (with progress) on a cache miss, the same way `get_beat_map` does.
- If stems are unavailable: `{"error": "Stem analysis unavailable. Install with: uv pip install -e \".[separation]\""}`.

## Packaging

- `beats` extra: `madmom @ git+https://github.com/CPJKU/madmom.git@27f032e8947204902c675e5e341a3faf5dc86dae`.
- `pyproject.toml`:
  ```toml
  [tool.uv.extra-build-dependencies]
  madmom = ["Cython", "setuptools", "numpy"]
  ```
  so `uv run` (without `--no-sync`) can build it. Verify during implementation; if uv 0.8 rejects the table, fall back to `no-build-isolation-package = ["madmom"]` and document the pre-install step.
- `_preload_audio_stack` also imports `madmom.features.downbeats` when available (same deadlock class as numpy/torch).
- README: note that `beats` needs a C compiler on Windows (MSVC Build Tools) and is optional.

## Testing

Unit tests use synthetic signals and fixtures; no audio files are added to the repo. Synthetic grids use 120 BPM (0.5 s beats, 2 s bars).

- **Silences**: energy curve with a known 3 s gap → one span within ±1 frame; a 0.5 s dip → no span.
- **Drum runs/gaps**: silences + onsets → expected runs; a single-onset raw run is discarded; a 2 s stop is a non-structural gap; decaying flag set when the silence starts > 1 s after the last onset.
- **Snap**: grid 45 ms late against onsets → every beat within 1 ms of its onset; a beat with the nearest onset 100 ms away is unchanged.
- **Re-anchor**: two anchor runs whose starts fall on beat 3 and beat 2 of the base count → each start is a downbeat, downbeats every 4 beats until the next anchor, backwards count before the first. An isolated crash inside a gap does not reset phase. No anchor runs → base downbeats unchanged.
- **Structure** (boundaries asserted on downbeats):
  - silent 0–20 s, run 20–60 s, gap 60–80 s (10 bars, decaying), run 80–120 s, silent 120–130 s → `intro, drop, breakdown (decaying), drop, outro`.
  - same, with a novelty boundary injected at 72 s → `intro, drop, breakdown, build, drop, outro`.
  - same, with novelty boundaries at 66 s and 72 s → `intro, drop, breakdown, breakdown, build, drop, outro` (only the last starts `build`).
  - drums from 0 s, gap 40–48 s (4 bars), run to end → `intro (present), build, drop`.
  - drums from 0 s with a 2 s stop at 40 s → fallback labeller, `structure_source = "stems"`.
  - drum stem with no onsets → fallback labeller, all `drums = "absent"`.
  - no stems → `structure_source = "mixdown"`, `drums = None`.
- **Engine**: every label in the vocabulary resolves in `SECTION_TYPE_CONFIG`.
- **Tool**: window clipping; truncation sets `next_start_ms` for onsets and energy; `beat` resolution yields one point per beat starting in the window, `bar` one per bar; invalid `stem`/`kind`/`resolution` errors; stems unavailable errors.
- **Cache**: a v1 entry is not loaded.

Manual integration check (not in CI), on the reference track: drops start on downbeats within 30 ms of 66.873 s and 140.388 s; breakdown starts within one beat of 110.086 s with `drums = "decaying"`; labels read intro → build → drop … breakdown (→ build) → drop … (outro).

All existing tests must still pass.
