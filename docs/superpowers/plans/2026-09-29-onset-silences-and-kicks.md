# Hit-bounded Silences and Kicks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `docs/superpowers/specs/2026-09-29-onset-silences-and-kicks-design.md`:
- hit-bounded stem silences, with an audible-hit filter and a roll veto for drums and an exit threshold for sustained stems;
- kick events;
- a `Kicks` timing track;
- baseline accents snapped to kicks.

**Architecture:**
- A new pure module, `audio/silences.py`, computes spans and kicks from the cached `SongAnalysis`. Stored analysis data is unchanged, and there's no cache version bump.
- `audio/stem_events.py` (the `get_stem_events` and `analyze_song` summaries), `sequencer/timing.py` (the Kicks track) and `sequencer/engine.py` (accent snapping) call it.

**Tech Stack:** Python 3.12, numpy, pydantic v2, FastMCP (mcp<2), pytest.

**Reference prototype:** `C:\Users\slick\AppData\Local\Temp\claude\E--\8c935770-b48a-44ae-b6a1-39ac9cf09310\scratchpad\xsong\` holds the scripts that validated these rules on eight songs:
- `rules.py`: the base rules;
- `variants.py`: `drums_v(..., hit_min=0.05, veto_median=0.15)`, the approved drum rule.

The implementation must match them. Task 6 checks parity.

---

## Ground rules

- **Branch:** `feat/onset-silences`, already created from `main`; the spec commits are on it. Don't rebase, switch branches or push.
- **Python:** `.venv/Scripts/python` only. Never `uv run`, `uv sync` or `uv pip install`.
- **Baseline:** `.venv/Scripts/python -m pytest -q` gives 575 passed, 1 deselected.
- **Commits:** one per task, using `git add <paths>` and then `git commit`. End the message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never `git commit -a`, `git add .`, `-A`, or `git stash`. Leave `uv.lock` untracked.
- **Style:** TDD; no comments that restate code; keep CRLF files CRLF (the working files are CRLF).
- **Scratchpad scripts:** write them with the Write tool and keep their output ASCII. A `Δ` crashed the cp1252 console before.
- **E:\XLights is read-only** for this plan.
- **Test helpers:**
  - `tests/show_fixtures.py`: `make_analysis(duration_s, beat_times, downbeat_times, path=..., **fields)`, which passes `stem_analysis=` through;
  - `tests/drum_fixtures.py`: `make_drum_stem(runs, duration, decay_s=0.0, onset_bass=None)`, which puts onsets every 0.5 s with energy 1.0 through each run;
  - `StemAnalysis` and `StemOnsets` live in `xlights_mcp.audio.stems_model`.

## File structure

| File | Change |
|---|---|
| `src/xlights_mcp/audio/silences.py` | create: `bounded_silences`, `kicks`, `nearest_kick` |
| `src/xlights_mcp/audio/stem_events.py` | `kicks` kind, bounded silences, `min_ms`/`merge_gap_ms`, stem alias, summary |
| `src/xlights_mcp/server.py` | `get_stem_events` parameters and docstring; `analyze_song` docstring note |
| `src/xlights_mcp/sequencer/timing.py` | `Kicks` track |
| `src/xlights_mcp/sequencer/engine.py` | accents snap to kicks |
| `src/xlights_mcp/prompts/sequence_song.md`, `README.md` | guidance |
| tests | `test_silences.py` (new), `test_stem_events.py`, `test_analyze_song_tool.py`, `test_timing_tracks.py`, `test_baseline.py`, `test_sequence_song_prompt.py` |

---

### Task 1: `audio/silences.py`

**Files:**
- Create: `src/xlights_mcp/audio/silences.py`
- Create: `tests/test_silences.py`

- [ ] **Step 1: Write the failing tests.**

  Build the fixtures with a small energy helper: frames every 0.02 s from 0 to the duration, level 0.0 except over `(start, end, level)` segments. Segments are applied in order, and a later segment overrides an earlier one. Use `make_analysis(16.0, beats, downbeats, stem_analysis=StemAnalysis(available=True, stems={...}))`, with 120 BPM beats (`np.arange(0, 16, 0.5)`) unless a case says otherwise. Each audible hit gets a segment `(h, h + 0.08, 0.8)`.

  Cases, with the expected result for each:

  **Drums**
  1. **Tail.**
     - Setup: hits every 0.5 s from 0.0 to 4.0, then 12.0 to 15.5. A tail at 0.2 over [4.08, 6.0).
     - Expected span: `[4.5, 12.0)`. `beat_after(4.0)` is 4.5, not the energy silence start of 6.0.
  2. **Ghost hits and bleed.**
     - Setup: as case 1, plus onsets at 9.0 and 10.0. Segments, in this order: bleed `(8, 12, 0.06)`, then ghosts `(8.9, 9.2, 0.02)` and `(9.9, 10.2, 0.02)`.
     - Expected: the span is unchanged, `[4.5, 12.0)`. The ghost onsets don't split it.
  3. **Roll veto.**
     - Setup: as case 1, but energy 0.5 over [5, 11.9) with no hits.
     - Expected: the span is dropped.
  4. **Hit just before a beat.**
     - Setup: the last hit of the first run is at 3.92 instead of 4.0.
     - Expected: the span starts at 4.5. 4.0 isn't later than 3.92 + 0.1.
  5. **Past the grid.**
     - Setup: beats stop at 10.0, and hits run 0–4 and 12.0–12.5 with nothing after.
     - Expected: the trailing span starts at `12.5 + 0.5` = 13.0.
  6. **Grid with fewer than 2 beats.**
     - Setup: `beat_times=[]`, with case 4's 3.92 hit.
     - Expected: the span starts at 4.42 (`3.92 + 0.5`), which the grid could never give.
  7. **Empty stem.**
     - Setup: no onsets, energy 0.
     - Expected: `[(0.0, 16.0)]`.
  8. **Duplicate onsets.**
     - Setup: case 1 with 2.0 listed twice.
     - Expected: the same result as case 1.

  **Sustained** (the `bass` stem, with stored `silences=[(4.0, 6.0)]`)
  1. **Rumble.**
     - Setup: energy 0.06 over [6.0, 7.5), 0.5 from 7.52. A hit at 7.55.
     - Expected end: 7.55.
  2. **Held note.**
     - Setup: energy 0.4 from 6.0 on, and no hits.
     - Expected end: 6.0, the stored end.
  3. **Never returns.**
     - Setup: energy 0.07 from 6.0 to the end.
     - Expected end: 16.0.
  4. **Joining.**
     - Setup: stored silences `[(2.0, 4.0), (4.3, 6.0)]`, energy 0.07 over [4.0, 4.3), 0.5 from 6.0.
     - Expected: one span, `[2.0, 6.0)`.
  5. **Hits inside a silence.**
     - Setup: a hit at 5.0, energy under 0.05.
     - Expected: the span isn't split, and the start stays 4.0.

  **Finishing**
  - Filtering happens before merging: drum hits every 0.45 s with no audible gaps at least 1 s long give `[]` with `merge_gap_ms=500`.
  - Test `_finish` directly for touching spans and clamping, which `bounded_silences` can't reach: `_finish([(1, 3), (3, 5), (14, 20)], 16, 1, 0) == [(1, 5), (14, 16)]`.
  - `min_ms=0` keeps short spans. Use off-grid drum hits every 0.45 s, which leave short gaps.

  **Kicks**
  - With `onset_bass` [0.3, 0.29, 0.9] at [1.0, 2.0, 3.0] plus a duplicate 3.0, the result is `[1.0, 3.0]`.
  - Each of these raises `ValueError`: no stems, no drums stem, and `onset_bass` of the wrong length.

  **`nearest_kick`**
  - `nearest_kick([19.94], 20.0)` is 19.94.
  - `nearest_kick([19.85], 20.0)` is `None`.
  - `nearest_kick([19.95, 20.04], 20.0)` is 20.04.
  - `nearest_kick([], 20.0)` is `None`.
  - A kick at 0.0 is returned as `0.0`, not treated as missing.

- [ ] **Step 2: Run the tests.** Run `.venv/Scripts/python -m pytest tests/test_silences.py -q`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement.**

```python
"""Stem silences bounded by audible hits, and kick times, from the cached analysis."""

from __future__ import annotations

import bisect
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np

from xlights_mcp.audio.drums import KICK_THRESHOLD, SILENCE_THRESHOLD

if TYPE_CHECKING:
    from xlights_mcp.audio.analyzer import SongAnalysis
    from xlights_mcp.audio.stems_model import StemOnsets

Span = tuple[float, float]

BEAT_TOLERANCE_S = 0.1
AUDIBLE_WINDOW_S = (0.03, 0.1)
ROLL_MEDIAN = 3 * SILENCE_THRESHOLD
EXIT_LEVEL = 2 * SILENCE_THRESHOLD
HIT_SNAP_S = 0.1
KICK_SNAP_S = 0.1
DEFAULT_BEAT_S = 0.5


def bounded_silences(
    analysis: SongAnalysis, stem: str, min_ms: int = 1000, merge_gap_ms: int = 0
) -> list[Span]:
    """Silences of a stem: drums bounded by audible hits, sustained stems ending where they return."""
    s = _stem(analysis, stem)
    duration = analysis.duration_seconds
    times = np.asarray(s.energy_times, dtype=float)
    energy = np.asarray(s.energy, dtype=float)
    hits = sorted(set(s.onset_times))
    if stem == "drums":
        spans = _drum_spans(hits, times, energy, analysis.beats.beat_times, duration)
    else:
        spans = _sustained_spans(s.silences, hits, times, energy, duration)
    return _finish(spans, duration, min_ms / 1000, merge_gap_ms / 1000)


def kicks(analysis: SongAnalysis) -> list[float]:
    """Drum hits with a kick's low end (onset_bass >= KICK_THRESHOLD), sorted and unique."""
    drums = _stem(analysis, "drums")
    if len(drums.onset_bass) != len(drums.onset_times):
        raise ValueError("kick levels don't line up with drum onsets; re-run analyze_song with force=true")
    return sorted({t for t, level in zip(drums.onset_times, drums.onset_bass) if level >= KICK_THRESHOLD})


def nearest_kick(kick_times: Sequence[float], t: float, window: float = KICK_SNAP_S) -> float | None:
    i = bisect.bisect_left(kick_times, t)
    near = [kick_times[k] for k in (i - 1, i) if 0 <= k < len(kick_times) and abs(kick_times[k] - t) <= window]
    return min(near, key=lambda k: abs(k - t)) if near else None


def _stem(analysis: SongAnalysis, name: str) -> StemOnsets:
    sa = analysis.stem_analysis
    if not sa.available:
        raise ValueError("stem analysis is unavailable for this song")
    if name not in sa.stems:
        raise ValueError(f"no {name} stem in this analysis")
    return sa.stems[name]


def _audible(t: float, times: np.ndarray, energy: np.ndarray) -> bool:
    if times.size == 0:
        return True
    before, after = AUDIBLE_WINDOW_S
    window = (times >= t - before) & (times <= t + after)
    return bool(window.any() and energy[window].max() >= SILENCE_THRESHOLD)


def _is_roll(start: float, end: float, times: np.ndarray, energy: np.ndarray) -> bool:
    inside = (times >= start) & (times < end)
    return bool(inside.any() and np.median(energy[inside]) >= ROLL_MEDIAN)


def _beat_after(beat_times: Sequence[float]) -> Callable[[float], float]:
    beats = sorted(beat_times)
    period = float(np.median(np.diff(beats))) if len(beats) >= 2 else DEFAULT_BEAT_S

    def after(t: float) -> float:
        if len(beats) >= 2:
            i = bisect.bisect_right(beats, t + BEAT_TOLERANCE_S)
            if i < len(beats):
                return beats[i]
        return t + period

    return after


def _drum_spans(hits, times, energy, beat_times, duration) -> list[Span]:
    audible = [h for h in hits if _audible(h, times, energy)]
    if not audible:
        candidates = [(0.0, duration)]
    else:
        after = _beat_after(beat_times)
        candidates = [
            (0.0, audible[0]),
            *((after(a), b) for a, b in pairwise(audible)),
            (after(audible[-1]), duration),
        ]
    return [(s, e) for s, e in candidates if e > s and not _is_roll(s, e, times, energy)]


def _sustained_spans(silences, hits, times, energy, duration) -> list[Span]:
    spans = []
    for start, end in silences:
        if times.size == 0:
            spans.append((start, end))
            continue
        back = (times >= end) & (energy >= EXIT_LEVEL)
        if back.any():
            frame = float(times[back][0])
            near = [h for h in hits if abs(h - frame) <= HIT_SNAP_S]
            spans.append((start, min(near, key=lambda h: abs(h - frame)) if near else frame))
        else:
            spans.append((start, duration))
    return spans


def _finish(spans: list[Span], duration: float, min_s: float, merge_gap_s: float) -> list[Span]:
    clamped = sorted((max(0.0, s), min(duration, e)) for s, e in spans)
    kept = [(s, e) for s, e in clamped if e > s and e - s >= min_s]
    merged: list[Span] = []
    for s, e in kept:
        if merged and (s <= merged[-1][1] or s - merged[-1][1] < merge_gap_s):
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged
```

Type-annotate the helper parameters (`list[float]`, `np.ndarray`, `Sequence[float]`, `list[tuple[float, float]]`) to match the rest of the module. They are elided above for space.

This differs from the prototype in one edge case that real data never hits: a stem with no energy frames. Here every hit counts as audible and the stored sustained end is kept; the prototype does the opposite.

- [ ] **Step 4: Run to pass.** Run `.venv/Scripts/python -m pytest tests/test_silences.py -q`.
- [ ] **Step 5: Commit** with the message "Hit-bounded stem silences and kick times".

### Task 2: `get_stem_events` and the `analyze_song` summary

**Files:**
- Modify: `src/xlights_mcp/audio/stem_events.py`, `src/xlights_mcp/server.py`
- Test: `tests/test_stem_events.py`, `tests/test_analyze_song_tool.py`

1. **`stem_events.py`:**
   - **Stems and kinds:**
     - `VALID_KINDS` adds `"kicks"`.
     - Add `STEM_ALIASES = {"instruments": "other"}` and `normalize_stem(stem) -> str`, which lowercases and then applies the alias.
   - **`validate_stem_query`:**
     - It gains `min_ms: int = 1000` and `merge_gap_ms: int = 0`.
     - It normalises the stem before checking it.
     - The unknown-stem message lists `drums, bass, vocals, other (or instruments)`.
     - New errors, checked for every kind:
       - `"kind 'kicks' needs stem 'drums'"`
       - `"min_ms must be >= 0"`
       - `"merge_gap_ms must be >= 0"`
   - **`stem_events(...)`:**
     - It gains `min_ms` and `merge_gap_ms` and normalises `stem`, so the response reports `"other"` for the alias.
     - **`kicks`:** `events_ms` from `kicks(analysis)`, windowed and truncated exactly like `onsets`. A `ValueError` becomes `{"error": str(e)}`.
     - **`silences`:** spans from `bounded_silences(analysis, stem, min_ms, merge_gap_ms)`, clipped to the window as today.
   - **`stems_summary`:** `silences_ms` uses `bounded_silences(analysis, name)`.
2. **`server.get_stem_events`:**
   - Add `min_ms: int = 1000` and `merge_gap_ms: int = 0` and pass them through, into validation too.
   - Update the docstring:
     - the kinds line (`onsets | energy | silences | kicks`);
     - the `kicks` paragraph;
     - the silences paragraph:
       - drum silences run from the beat after the last audible hit to the next one;
       - bass, instruments and vocals silences end where the stem clearly returns;
       - a drum silence can end on a pickup, so use `kicks` for the drop hit;
       - `merge_gap_ms` of about 150–500 joins split dropouts;
       - raise `min_ms` to about a bar for sparse material;
     - the stem line (`drums | bass | vocals | other (alias: instruments)`).
3. **`analyze_song` docstring:** `stems.silences_ms` uses the same bounded spans, while `sections[].drums` still comes from the energy-based structure analysis.
4. **Tests:**
   - `test_analyze_song_tool.py::test_analyze_song_reports_stem_summary_and_provenance` asserts `[[7755, 12005]]`. With runs (0, 8) and (12, 20), 0.5 s beats and energy 1.0 in the runs, the bounded drum span is `[8000, 12000]`: `beat_after(7.5)` is 8.0 and the next hit is 12.0. Update the assertion.
   - `test_stem_events.py::test_summary_reports_counts_energy_and_silences_in_ms` asserts `7700 < start < 7900`; the start becomes 8000.
   - The "~7755-12005ms" comment in `test_silences_zero_length_window_returns_empty` is now stale.
   - Recompute any other silence expectations in `test_stem_events.py` the same way, and state the derivation in a short comment where the number isn't obvious.
   - New tests:
     - `kicks` events (and truncation), and kicks with `stem="bass"` giving an error;
     - `instruments` and `Instruments` resolving to `other`;
     - `min_ms` and `merge_gap_ms` changing silences, and the negative-value errors;
     - `get_stem_events` through the MCP session (see the existing tool tests) with `kind="kicks"` and with the alias.
5. **Commit** with the message "get_stem_events: kicks, hit-bounded silences, instruments alias".

### Task 3: `Kicks` timing track and snapped accents

**Files:**
- Modify: `src/xlights_mcp/sequencer/timing.py`, `src/xlights_mcp/sequencer/engine.py`
- Test: `tests/test_timing_tracks.py`, `tests/test_baseline.py` (and `tests/test_engine_auto.py` if it asserts the stem track list)

1. **`timing.py`:**
   - Set `STEM_TRACK_NAMES = (*_STEM_TRACKS, "Kicks")`. `TIMING_TRACK_NAMES` follows automatically.
   - In `build_timing_tracks`, add an `elif name == "Kicks":` branch before the `_STEM_TRACKS` branch. It calls `kicks(analysis)`:
     - on `ValueError`, or with no kicks, warn `"Kicks timing track skipped: {reason}"` and `continue`;
     - otherwise the marks are `_marks(kick_times, ["x"] * n, end_ms)`.
2. **`engine._baseline_placements`:**
   - Compute `kick_times` once: `kicks(analysis)` inside `try`/`except ValueError`, falling back to `[]`.
   - For each accent downbeat, `k = nearest_kick(kick_times, downbeat)`, then `at = to_frame((downbeat if k is None else k) * 1000)`. Keep the last-frame guard.
3. **Docs that list the stem tracks:** add `Kicks` in each of these:
   - the `create_sequence` docstring (server.py, around line 635);
   - the `write_sequence` `timing_tracks` argument (server.py, around lines 738–739);
   - the README's baseline paragraph (around line 334).
4. **Tests:**
   - **Kicks track:**
     - The existing `_analysis(stems=True)` in `test_timing_tracks.py` has no `onset_bass`, so `kicks()` raises there; build the drums stem with explicit `onset_bass` for the "track is built" case.
     - Marks are made for the kicks, and no stems or no kicks each give a warning.
     - `"Kicks"` is in `TIMING_TRACK_NAMES`.
   - **Baseline snap:** use the existing chorus case in `test_baseline.py` and add a drums stem.
     - A kick at 19.94 moves the 20.0 accent to `to_frame(19940)` = 19950.
     - A kick at 19.85 leaves it at 20000.
     - Without stems, accents are unchanged.
   - **Baseline track list:** no existing test runs `create_sequence` with stems. In `test_engine_auto.py`, where the `audio` fixture caches a `make_analysis`, add a test whose analysis carries `stem_analysis=StemAnalysis(available=True, stems={"drums": make_drum_stem(...)})` and assert `"Kicks"` is in `result["timing_tracks"]`.
5. **Commit** with the message "Kicks timing track; baseline accents snap to kicks".

### Task 4: Playbook and README

**Files:**
- Modify: `src/xlights_mcp/prompts/sequence_song.md`, `README.md`
- Test: `tests/test_sequence_song_prompt.py`

1. **`sequence_song.md`, step 1:**
   - Time dropouts from `get_stem_events(kind="silences")`, with `merge_gap_ms` to join split dropouts.
   - Time hits from `kind="kicks"` (drums).
   - In step 5, list `"Kicks"` beside Beats and Bars when stems are available.
   - Add a prompt test pinning `kind="kicks"`.
2. **README:**
   - The `get_stem_events` row mentions `kicks` and the bounded silences.
   - The `write_sequence` row's timing tracks mention `Kicks`.
3. **Commit** with the message "Playbook and README: silences for dropouts, kicks for hits".

### Task 5: Full suite

- Run `.venv/Scripts/python -m pytest -q`: everything passes.
- Run `ruff check` on the changed files: no new findings.

### Task 6: Parity and manual checks

Write `C:\Users\slick\AppData\Local\Temp\claude\E--\8c935770-b48a-44ae-b6a1-39ac9cf09310\scratchpad\xsong\parity.py`. It loads each of the eight songs with `full_analysis(path, load_config().audio)`; all are cached. The songs:
- `E:\XLights\HalloweenShow\Music\GhostsnStuffft.RobSwire.mp3`
- `E:\XLights\ChristmasShow\Music\Deck the Halls Remix.mp3`
- `E:\XLights\ChristmasShow\Music\4B - Carnival (feat. Bunji Garlin) (Xmas Edition).mp3`
- `E:\XLights\HalloweenShow\Music\Corpse Bride - Remains of the Day.mp3`
- `E:\XLights\ChristmasShow\Music\Idina Menzel - Let It Go (From _Frozen__Soundtrack Version).mp3`
- `E:\XLights\HalloweenShow\Music\Superstition.mp3`
- `E:\XLights\ChristmasShow\Music\Pentatonix - Dance of the Sugar Plum Fairy.mp3`
- `E:\XLights\HalloweenShow\Music\Beetlejuice - Main title.mp3`

For each song, the script compares:
- `bounded_silences(a, "drums")` with `variants.drums_v(Song(a), hit_min=0.05, veto_median=0.15)`;
- `bounded_silences(a, name)` for bass, other and vocals with `rules.Song(a).sustained(name)`;
- `kicks(a)` with `rules.Song(a).kicks()`.

Spans must match to 1 ms. It prints the Ghosts checks, all of which must hold:
- drums: `[0, 7.036), [51.710, 65.945), [110.540, 139.482), [184.041, 187.288)`;
- the bridge bass silence ends at 125.272, and the intro bass at about 7.709;
- drums are silent across 125.4–129.8;
- 252 kicks;
- the baseline accents at 79.290, 103.180, 149.140 and 169.360 move onto kicks.

Report any mismatch. Don't change the code to fit the prototype without understanding why they differ.
