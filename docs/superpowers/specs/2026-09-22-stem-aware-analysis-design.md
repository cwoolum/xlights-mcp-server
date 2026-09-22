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
2. Section labels derived from drum presence, with an EDM vocabulary; pop songs keep the current labeller.
3. Per-stem data reachable through a tool, sized for an LLM.
4. Everything degrades to today's behaviour when stems are unavailable, and says so.

Non-goals: changes to `create_sequence` output (PR B), `get_beat_map` / `get_energy_profile` size fixes (PR C, #6 #7).

## Pipeline

`full_analysis` order becomes:

1. spectrum
2. stems — separate, then `analyze_stems` (now also computes `silences`)
3. beats — receives drum onsets and drum silences, or `None`
4. structure — receives the drum stem analysis and the beat map, or `None`

Progress still reports 5 stages, in the new order. If separation or stem analysis fails, stages 3–4 receive `None` and behave exactly as today.

## Data model changes

`StemOnsets` (audio/analyzer.py) gains:

```python
silences: list[tuple[float, float]]  # seconds, [start, end)
```

A silence is a span where the stem's normalised RMS stays below `SILENCE_THRESHOLD = 0.05` for at least `MIN_SILENCE_S = 1.0`. Computed once in `analyze_stems` for every stem. Every consumer (beat re-anchoring, structure, `get_stem_events`, the `analyze_song` summary) reads this list; none re-derives silence.

**Drum runs** are the complement of the drum stem's silences within `[0, duration]`. A run's *start* is the first drum onset at or after the silence end. A run's *end* is the last drum onset before the next silence begins. Runs with no onsets are discarded.

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

## Beat grid

In `detect_beats(audio_path, sr, drum_onsets=None, drum_silences=None)`:

1. **Base grid.** madmom `RNNDownBeatProcessor` + `DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)` if madmom imports; otherwise librosa `beat_track`. madmom's bar positions are discarded. `beat_source` records which ran. Tempo = 60 / median inter-beat interval.
2. **Snap** (only when `drum_onsets` given). Each beat moves to the nearest drum onset within ±60 ms. Beats with no drum onset in range keep their position.
3. **Re-anchor downbeats** (only when drum runs exist). For each drum run, the snapped beat nearest its start is beat 1; every 4th beat after it is a downbeat until the next run's anchor. Beats before the first run count backwards from the first anchor, so the intro and first riser keep a bar grid consistent with drop 1.
4. `drum_aligned = True` when steps 2–3 ran.
5. `onset_times` stays the mixdown onsets. Per-stem onsets are served by `get_stem_events`.

Measured on the reference track: madmom beats land within +7 / −16 / +22 ms of the three drum events but its downbeats are 438–467 ms off at both drops, which is why step 3 overrides bar phase regardless of source.

## Structure

With the drum stem available (`structure_source = "stems"`):

1. **Boundaries.** Candidates are drum-run starts, drum-run ends, and the existing novelty/energy boundaries. A novelty boundary within 2 s of a drum boundary is dropped in favour of the drum boundary. Every boundary then snaps to the nearest downbeat. Sections shorter than one bar merge into their predecessor.
2. **Labels**, assigned per section by drum state, position and energy:

   | Condition | Label | `drums` |
   |---|---|---|
   | Before the first drum run | `intro` | `absent` |
   | First section, drums present from the start (no leading silence) | `intro` | `present` |
   | Mid-song drum gap of ≤ 8 bars | `build` | `absent`, or `decaying` (see below) |
   | Mid-song drum gap of > 8 bars | `breakdown`; if a novelty/energy boundary falls inside the gap, the part after it is `build` | `breakdown`: `decaying` or `absent`; `build`: `absent` |
   | Starts at a drum-run start that follows ≥ 4 s of drum silence | `drop` | `present` |
   | After the last drum run | `outro` | `absent` or `decaying` |
   | Drums present, none of the above (e.g. second half of a long drop) | inherits the preceding section's label | `present` |

   A gap section is `decaying` when more than 1 s separates the run's last drum onset from the start of the silence span (the stem tails off rather than cutting). The section boundary is always the last onset, not the silence start.

   On the reference track the ~10 s gap before drop 1 (≈ 5 bars) is a `build`; the ~30 s gap from 110.086 s (≈ 16 bars) is a `breakdown`, with a trailing `build` if novelty marks the riser.

3. **Pop fallback.** If the drum stem has no silences between its first and last onset (drums steady throughout), use today's repetition labeller for labels, keep the drum-derived boundaries, and set `drums` per section from the stem.
4. `confidence` = 0.9 for drum-derived labels, 0.65 for fallback labels (unchanged).

Without stems: today's algorithm, `structure_source = "mixdown"`, `drums = None`.

Expected on the reference track: `intro, build, drop, …, breakdown, build, drop, …, outro`, with drop 1 starting at the downbeat nearest 66.873 s, breakdown at the downbeat nearest 110.086 s (`drums = "decaying"`), drop 2 at the downbeat nearest 140.388 s.

### Engine compatibility

`SECTION_TYPE_CONFIG` in sequencer/engine.py gains three aliases so `create_sequence` output is unchanged by this PR: `build` → `transition` config, `drop` → `chorus` config, `breakdown` → `bridge` config.

## Tool surface

### `analyze_song` response additions

```json
"beat_source": "madmom",
"drum_aligned": true,
"structure_source": "stems",
"stems": {
  "drums":  {"onsets": 533, "mean_energy": 0.41, "silences_ms": [[57100, 66870], [110090, 140380]]},
  "bass":   {"onsets": 156, "mean_energy": 0.33, "silences_ms": [...]},
  "vocals": {"onsets": 415, "mean_energy": 0.22, "silences_ms": [...]},
  "other":  {"onsets": 190, "mean_energy": 0.37, "silences_ms": [...]}
}
```

`stems` is `null` when stems are unavailable. Each section entry gains `drums`. All times in this block are integer milliseconds. No file paths are returned.

### New tool: `get_stem_events`

```
get_stem_events(mp3_path: str, stem: str, kind: str,
                start_ms: int | None = None, end_ms: int | None = None,
                max_events: int = 500, resolution: str = "beat") -> dict
```

- `stem` ∈ `drums | bass | vocals | other`; `kind` ∈ `onsets | energy | silences`. Invalid values return `{"error": ...}` listing the valid ones.
- Window `[start_ms, end_ms)` defaults to the whole track.
- `onsets` → `{"stem", "kind", "count", "events_ms": [int, ...]}`. If more than `max_events` fall in the window, return the first `max_events`, plus `"truncated": true` and `"next_start_ms"`.
- `energy` → `{"stem", "kind", "resolution", "points": [{"t_ms": int, "energy": float (3 dp)}]}`. `resolution="beat"` gives one mean value per beat of the (re-phased) grid; `"bar"` one per downbeat-to-downbeat span. `max_events` truncation applies to points.
- `silences` → `{"stem", "kind", "spans_ms": [[start, end], ...]}`, clipped to the window.
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

Unit tests use synthetic signals and fixtures; no audio files are added to the repo.

- **Silences**: energy curve with a known 3 s gap → one span within ±1 frame; a 0.5 s dip → no span.
- **Drum runs**: silences + onsets → expected run starts/ends; a run with no onsets is discarded.
- **Snap**: grid 45 ms late against onsets → every beat within 1 ms of its onset; a beat with the nearest onset 100 ms away is unchanged.
- **Re-anchor**: two runs whose starts fall on beat 3 and beat 2 of the base grid's count → the beat at each run start is a downbeat, and downbeats repeat every 4 beats until the next anchor; beats before the first run have downbeats counted backwards.
- **Beat fallback**: no drum data → `drum_aligned = False`, grid equals base grid.
- **Structure** (120 BPM synthetic grid, 2 s bars), boundaries asserted on downbeats:
  - silent 0–20 s, run 20–60 s, gap 60–80 s (10 bars, 2 s decay), run 80–120 s, silent after → `intro, drop, breakdown (decaying), drop, outro`.
  - same, with a novelty boundary injected at 72 s → `intro, drop, breakdown, build, drop, outro`.
  - drums from 0 s, gap 40–48 s (4 bars), run to end → `intro (present), build, drop`.
  - steady drums throughout → fallback labels, `structure_source = "stems"`.
  - no stems → `structure_source = "mixdown"`, `drums = None`.
- **Engine**: every label in the vocabulary resolves in `SECTION_TYPE_CONFIG`.
- **Tool**: window clipping; truncation sets `next_start_ms`; `energy` beat resolution yields one point per beat in the window; bar resolution one per bar; invalid `stem`/`kind` errors; stems unavailable errors.
- **Cache**: version bump — a v1 entry is not loaded.

Manual integration check (not in CI), on the reference track: drops start on downbeats within 30 ms of 66.873 s and 140.388 s; breakdown starts within one beat of 110.086 s with `drums = "decaying"`; labels read intro → build → drop … breakdown → build → drop … outro.

All existing tests must still pass.
