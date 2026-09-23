# Stem-Aware Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the beat grid to the drum stem, derive honest (EDM-aware) section labels from drum presence, and expose per-stem data through a new `get_stem_events` MCP tool.

**Architecture:** A new `audio/drums.py` owns the shared primitives (silences, runs, gaps, anchors). `beats.py` snaps and re-anchors the grid with them; a new `audio/edm_structure.py` labels sections from them; `structure.py` picks EDM vs. existing labelling. `full_analysis` runs stems *before* beats and structure so both can use the drum stem. A new `audio/stem_events.py` turns cached analysis into LLM-sized payloads for `analyze_song` and `get_stem_events`.

**Tech Stack:** Python 3.12, librosa 1.0, numpy, pydantic v2, mcp 1.x (FastMCP), optional madmom (git master), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md` — read it before starting.

---

## Conventions for every task

- Working dir: `E:\xlights-mcp-server`, branch `feat/stem-aware-analysis`.
- Python: always `.venv/Scripts/python` (Git Bash) — never bare `python` (that is a different interpreter without the deps).
- Never run `uv run` or `uv sync` in this repo: it rebuilds the environment and would replace the CUDA torch build. Use `uv pip install` only.
- Run a single test: `.venv/Scripts/python -m pytest tests/<file>.py::<test> -v`
- Full suite: `.venv/Scripts/python -m pytest -q` (takes ~30 s; one test runs demucs).
- Lint: `.venv/Scripts/python -m ruff check <files you created or changed>`. The repo already has ~44 findings in files this plan never touches (e.g. `lyrics.py`, `separator.py`, `spectrum.py`, several tests) and some in `server.py`. Fix findings only in lines you wrote or changed; never "clean up" other files.
- Comments: only where the *why* is non-obvious. Don't restate code.
- Commit message trailer on every commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

## File map

| File | Status | Responsibility |
|---|---|---|
| `src/xlights_mcp/audio/stems_model.py` | create | `StemOnsets` (+ `silences`), `StemAnalysis` — moved out of analyzer.py, no deps on other audio modules |
| `src/xlights_mcp/audio/sections.py` | create | `SongSection` (+ `structure_source`, `drums`), `SECTION_LABELS` — moved out of structure.py |
| `src/xlights_mcp/audio/drums.py` | create | `find_silences`, `DrumRun`, `DrumGap`, `drum_runs`, `drum_gaps`, `anchor_starts`, `has_mid_structural_gap`, `run_coverage` |
| `src/xlights_mcp/audio/edm_structure.py` | create | `label_edm_sections` |
| `src/xlights_mcp/audio/stem_events.py` | create | `stems_summary`, `validate_stem_query`, `stem_events` |
| `src/xlights_mcp/audio/analyzer.py` | modify | re-export moved models; silences in `analyze_stems`; pipeline reorder |
| `src/xlights_mcp/audio/beats.py` | modify | `BeatMap` fields; `snap_beats`, `anchor_downbeats`, `_madmom_grid`; new `detect_beats` |
| `src/xlights_mcp/audio/structure.py` | modify | re-export `SongSection`; `detect_structure(…, drums, beats)` with mode selection |
| `src/xlights_mcp/audio/cache.py` | modify | `ANALYSIS_VERSION = 2` |
| `src/xlights_mcp/sequencer/engine.py` | modify | label aliases in `SECTION_TYPE_CONFIG` |
| `src/xlights_mcp/server.py` | modify | `analyze_song` fields; `get_stem_events` tool; madmom in preload |
| `pyproject.toml`, `README.md` | modify | `beats` extra → madmom git pin |
| `tests/drum_fixtures.py` | create | `make_drum_stem` synthetic stem builder shared by tests |
| `tests/test_drums.py`, `tests/test_beat_grid.py`, `tests/test_edm_structure.py`, `tests/test_structure_modes.py`, `tests/test_stem_events.py`, `tests/test_pipeline_order.py`, `tests/test_engine_labels.py` | create | unit tests |
| `tests/test_analysis_cache.py`, `tests/test_analyze_song_tool.py` | modify | cache version test; tool tests |

---

### Task 0: Commit the in-progress cache/progress work

The working tree already contains uncommitted work that this plan builds on (analysis cache, progress reporting, their tests). Commit it as-is so the rest of the branch has a clean base.

**Files:** `src/xlights_mcp/audio/cache.py`, `src/xlights_mcp/audio/analyzer.py`, `src/xlights_mcp/sequencer/engine.py`, `src/xlights_mcp/server.py`, `tests/conftest.py`, `tests/test_analysis_cache.py`, `tests/test_analyze_song_tool.py`

- [ ] **Step 1: Confirm the suite passes on the uncommitted tree**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `130 passed`

- [ ] **Step 2: Commit**

```bash
git add src/xlights_mcp/audio/cache.py src/xlights_mcp/audio/analyzer.py src/xlights_mcp/sequencer/engine.py src/xlights_mcp/server.py tests/conftest.py tests/test_analysis_cache.py tests/test_analyze_song_tool.py
git commit -m "Cache song analysis on disk and stream stage progress" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git status --short
```
Expected: `git status --short` prints nothing.

---

### Task 1: Move stem and section models into dependency-free modules

Pure refactor, needed so `drums.py` / `edm_structure.py` can import the models without an import cycle (`analyzer` → `beats` → `drums` → `analyzer`).

**Files:**
- Create: `src/xlights_mcp/audio/stems_model.py`
- Create: `src/xlights_mcp/audio/sections.py`
- Modify: `src/xlights_mcp/audio/analyzer.py` (remove `StemOnsets`, `StemAnalysis` class bodies, lines ~21–60)
- Modify: `src/xlights_mcp/audio/structure.py` (remove `SongSection` class, lines ~14–34)

- [ ] **Step 1: Create `stems_model.py`** by moving the two classes verbatim from analyzer.py, plus the new `silences` field:

```python
"""Per-stem onset/energy models, kept free of other audio-module imports."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field


class StemOnsets(BaseModel):
    """Onset and energy analysis for a single audio stem."""

    name: str  # "drums", "bass", "other", "vocals"
    onset_times: list[float] = Field(default_factory=list)  # seconds
    energy: list[float] = Field(default_factory=list)  # normalized 0-1 per frame
    energy_times: list[float] = Field(default_factory=list)  # seconds
    mean_energy: float = 0.0
    silences: list[tuple[float, float]] = Field(default_factory=list)  # seconds, [start, end)


class StemAnalysis(BaseModel):
    """Onset and energy analysis for all separated stems."""

    available: bool = False
    stems: dict[str, StemOnsets] = Field(default_factory=dict)  # name → StemOnsets

    def get_onsets_in_range(self, stem: str, start: float, end: float) -> list[float]:
        """Get onset times for a stem within a time range."""
        if stem not in self.stems:
            return []
        return [t for t in self.stems[stem].onset_times if start <= t < end]

    def get_mean_energy_in_range(self, stem: str, start: float, end: float) -> float:
        """Get mean energy for a stem within a time range."""
        if stem not in self.stems:
            return 0.0
        s = self.stems[stem]
        energies = [e for t, e in zip(s.energy_times, s.energy) if start <= t < end]
        return float(np.mean(energies)) if energies else 0.0

    def dominant_stem(self, start: float, end: float) -> str:
        """Return the stem name with highest mean energy in a time range."""
        best_name = "other"
        best_energy = 0.0
        for name in self.stems:
            e = self.get_mean_energy_in_range(name, start, end)
            if e > best_energy:
                best_energy = e
                best_name = name
        return best_name
```

This is the existing `StemAnalysis` except `dominant_stem` iterates `self.stems` keys (the value was unused — ruff PERF102); only `StemOnsets.silences` is new.

- [ ] **Step 2: In analyzer.py**, delete both class definitions and add to the imports:

```python
from xlights_mcp.audio.stems_model import StemAnalysis, StemOnsets
```

Both names are still used in analyzer.py (`analyze_stems`, `SongAnalysis`), and `engine.py` keeps importing `StemAnalysis` from `analyzer`.

- [ ] **Step 3: Create `sections.py`** by moving `SongSection` verbatim from structure.py and adding the new fields and vocabulary:

```python
"""Song section model and the label vocabulary shared by structure detection and the engine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SECTION_LABELS: tuple[str, ...] = (
    "intro", "build", "drop", "breakdown", "outro",
    "verse", "chorus", "bridge", "transition", "instrumental",
)


class SongSection(BaseModel):
    """A detected section of a song."""

    label: str  # one of SECTION_LABELS
    start_time: float  # seconds
    end_time: float  # seconds
    energy_level: float = 0.0  # 0.0-1.0 average energy
    confidence: float = 0.0
    structure_source: Literal["stems", "mixdown"] = "mixdown"
    drums: Literal["present", "absent", "decaying"] | None = None

    @property
    def start_time_ms(self) -> int:
        return int(self.start_time * 1000)

    @property
    def end_time_ms(self) -> int:
        return int(self.end_time * 1000)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
```

- [ ] **Step 4: In structure.py**, delete the class and import it:

```python
from xlights_mcp.audio.sections import SongSection
```

`engine.py` keeps importing `SongSection` from `structure` — that still resolves. Delete `from pydantic import BaseModel, Field` from structure.py; nothing else there uses it.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `130 passed`

- [ ] **Step 6: Commit**

```bash
git add src/xlights_mcp/audio/stems_model.py src/xlights_mcp/audio/sections.py src/xlights_mcp/audio/analyzer.py src/xlights_mcp/audio/structure.py
git commit -m "Move stem and section models into dependency-free modules" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `find_silences` and the synthetic drum-stem fixture

**Files:**
- Create: `src/xlights_mcp/audio/drums.py`
- Create: `tests/drum_fixtures.py`
- Create: `tests/test_drums.py`

- [ ] **Step 1: Write the failing tests** in `tests/test_drums.py`:

```python
"""Tests for drum-stem silences, runs and gaps."""

from __future__ import annotations

import numpy as np
import pytest

from xlights_mcp.audio.drums import find_silences

HOP = 512 / 22050


def _curve(duration: float, quiet: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    times = np.arange(0, duration, HOP)
    energy = np.ones_like(times)
    for a, b in quiet:
        energy[(times >= a) & (times < b)] = 0.0
    return energy, times


def test_find_silences_detects_a_three_second_gap():
    energy, times = _curve(10.0, [(4.0, 7.0)])

    spans = find_silences(energy, times, end=10.0)

    assert len(spans) == 1
    start, end = spans[0]
    assert start == pytest.approx(4.0, abs=HOP)
    assert end == pytest.approx(7.0, abs=HOP)


def test_find_silences_ignores_dips_shorter_than_one_second():
    energy, times = _curve(10.0, [(4.0, 4.5)])

    assert find_silences(energy, times, end=10.0) == []


def test_find_silences_closes_a_silence_running_to_the_end():
    energy, times = _curve(10.0, [(8.0, 10.0)])

    spans = find_silences(energy, times, end=10.0)

    assert spans == [(pytest.approx(8.0, abs=HOP), 10.0)]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_drums.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xlights_mcp.audio.drums'`

- [ ] **Step 3: Create `drums.py`** with the constants and `find_silences`:

```python
"""Drum-stem runs and gaps: the shared primitive behind beat re-anchoring and EDM structure.

See docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md, "Drum runs and gaps".
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

import numpy as np
from pydantic import BaseModel

from xlights_mcp.audio.stems_model import StemOnsets

SILENCE_THRESHOLD = 0.05
MIN_SILENCE_S = 1.0
STRUCTURAL_GAP_S = 4.0
DECAY_S = 1.0
BEATS_PER_BAR = 4
# Backtracked onsets can land a few frames before the energy crosses the threshold.
_EDGE_TOLERANCE_S = 0.1


def find_silences(
    energy: np.ndarray,
    times: np.ndarray,
    end: float,
    threshold: float = SILENCE_THRESHOLD,
    min_len: float = MIN_SILENCE_S,
) -> list[tuple[float, float]]:
    """Spans where normalised energy stays below threshold for at least min_len seconds."""
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for t, e in zip(times, energy):
        if e < threshold:
            if start is None:
                start = float(t)
        elif start is not None:
            if t - start >= min_len:
                spans.append((start, float(t)))
            start = None
    if start is not None and end - start >= min_len:
        spans.append((start, float(end)))
    return spans
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_drums.py -v`
Expected: 3 passed

- [ ] **Step 5: Create `tests/drum_fixtures.py`** (used from Task 3 on):

```python
"""Synthetic drum stems for tests: onsets every half second inside each run."""

from __future__ import annotations

import numpy as np

from xlights_mcp.audio.drums import find_silences
from xlights_mcp.audio.stems_model import StemOnsets

HOP = 512 / 22050


def make_drum_stem(
    runs: list[tuple[float, float]], duration: float, decay_s: float = 0.0, name: str = "drums"
) -> StemOnsets:
    """Onsets every 0.5 s in each [start, end) run; energy 1.0 through each run,
    then a linear decay over decay_s seconds after the run's last onset."""
    times = np.arange(0, duration, HOP)
    energy = np.zeros_like(times)
    onsets: list[float] = []
    for a, b in runs:
        run_onsets = np.arange(a, b, 0.5)
        onsets.extend(float(t) for t in run_onsets)
        tail = run_onsets[-1] + 0.25
        energy[(times >= a) & (times <= tail)] = 1.0
        if decay_s > 0:
            fading = (times > tail) & (times <= tail + decay_s)
            energy[fading] = np.maximum(energy[fading], 1.0 - (times[fading] - tail) / decay_s)
    return StemOnsets(
        name=name,
        onset_times=onsets,
        energy=energy.tolist(),
        energy_times=times.tolist(),
        mean_energy=float(energy.mean()),
        silences=find_silences(energy, times, end=duration),
    )
```

- [ ] **Step 6: Commit**

```bash
git add src/xlights_mcp/audio/drums.py tests/test_drums.py tests/drum_fixtures.py
git commit -m "Add drum-stem silence detection" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Drum runs, gaps, anchors, coverage

**Files:**
- Modify: `src/xlights_mcp/audio/drums.py`
- Modify: `tests/test_drums.py`

All tests use 120 BPM: `beat_period = 0.5`, one bar = 2.0 s.

- [ ] **Step 1: Append failing tests** to `tests/test_drums.py`:

```python
from drum_fixtures import make_drum_stem

from xlights_mcp.audio.drums import (
    anchor_starts,
    drum_gaps,
    drum_runs,
    has_mid_structural_gap,
    run_coverage,
)

PERIOD = 0.5


def test_drum_runs_span_first_to_last_onset_of_each_stretch():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)

    runs = drum_runs(stem, PERIOD, duration=130)

    assert [(r.start, r.end) for r in runs] == [(20.0, 59.5), (80.0, 119.5)]


def test_drum_runs_discard_an_isolated_hit():
    stem = make_drum_stem([(20, 60), (70, 70.5), (80, 120)], duration=130)

    runs = drum_runs(stem, PERIOD, duration=130)

    assert [r.start for r in runs] == [20.0, 80.0]


def test_drum_gaps_classify_leading_mid_trailing():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)
    runs = drum_runs(stem, PERIOD, duration=130)

    gaps = drum_gaps(runs, stem, duration=130, beat_period=PERIOD)

    assert [g.kind for g in gaps] == ["leading", "mid", "trailing"]
    mid = gaps[1]
    assert (mid.start, mid.end) == (59.5, 80.0)
    assert mid.bars == pytest.approx(20.5 / 2.0)
    assert all(g.structural for g in gaps)


def test_short_drum_stop_is_not_structural():
    stem = make_drum_stem([(0, 40), (42, 60)], duration=60)
    runs = drum_runs(stem, PERIOD, duration=60)

    gaps = drum_gaps(runs, stem, duration=60, beat_period=PERIOD)

    assert [g.kind for g in gaps] == ["mid", "trailing"]
    assert gaps[0].structural is False
    assert has_mid_structural_gap(gaps) is False


def test_gap_is_decaying_when_silence_starts_over_a_second_after_last_onset():
    fading = make_drum_stem([(20, 60), (80, 120)], duration=130, decay_s=2.0)
    cutting = make_drum_stem([(20, 60), (80, 120)], duration=130)

    fade_gaps = drum_gaps(drum_runs(fading, PERIOD, 130), fading, 130, PERIOD)
    cut_gaps = drum_gaps(drum_runs(cutting, PERIOD, 130), cutting, 130, PERIOD)

    assert fade_gaps[1].decaying is True
    assert cut_gaps[1].decaying is False
    assert fade_gaps[0].decaying is False  # leading gaps never decay


def test_anchor_starts_are_run_starts_after_structural_gaps():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)
    gaps = drum_gaps(drum_runs(stem, PERIOD, 130), stem, 130, PERIOD)

    assert anchor_starts(gaps) == [20.0, 80.0]
    assert has_mid_structural_gap(gaps) is True


def test_no_onsets_means_no_runs_and_no_gaps():
    from xlights_mcp.audio.stems_model import StemOnsets

    stem = StemOnsets(name="drums", silences=[(0.0, 30.0)])

    runs = drum_runs(stem, PERIOD, duration=30)

    assert runs == []
    assert drum_gaps(runs, stem, 30, PERIOD) == []


def test_run_coverage_is_fraction_of_window_inside_runs():
    stem = make_drum_stem([(20, 60), (80, 120)], duration=130)
    runs = drum_runs(stem, PERIOD, 130)

    assert run_coverage(runs, 0, 20) == 0.0
    assert run_coverage(runs, 30, 50) == 1.0
    assert run_coverage(runs, 50, 70) == pytest.approx(9.5 / 20)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_drums.py -v`
Expected: FAIL — `ImportError: cannot import name 'anchor_starts'`

- [ ] **Step 3: Implement** — append to `drums.py`:

```python
class DrumRun(BaseModel):
    start: float  # first onset, seconds
    end: float  # last onset, seconds


class DrumGap(BaseModel):
    start: float
    end: float
    bars: float
    kind: Literal["leading", "mid", "trailing"]
    structural: bool
    decaying: bool


def drum_runs(drums: StemOnsets, beat_period: float, duration: float) -> list[DrumRun]:
    """Stretches between drum silences that hold at least one bar of onsets."""
    onsets = np.sort(np.asarray(drums.onset_times, dtype=float))
    stretches: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in sorted(drums.silences):
        stretches.append((cursor, start))
        cursor = end
    stretches.append((cursor, duration))

    min_len = BEATS_PER_BAR * beat_period - 1e-6
    runs: list[DrumRun] = []
    for a, b in stretches:
        inside = onsets[(onsets >= a - _EDGE_TOLERANCE_S) & (onsets < b + _EDGE_TOLERANCE_S)]
        if inside.size and inside[-1] - inside[0] >= min_len:
            runs.append(DrumRun(start=float(inside[0]), end=float(inside[-1])))
    return runs


def drum_gaps(
    runs: list[DrumRun], drums: StemOnsets, duration: float, beat_period: float
) -> list[DrumGap]:
    """Leading, between-run and trailing gaps, measured last onset to next first onset."""
    if not runs:
        return []
    bar = BEATS_PER_BAR * beat_period
    spans: list[tuple[str, float, float, DrumRun | None]] = []
    if runs[0].start > 0:
        spans.append(("leading", 0.0, runs[0].start, None))
    for prev, nxt in pairwise(runs):
        spans.append(("mid", prev.end, nxt.start, prev))
    if runs[-1].end < duration:
        spans.append(("trailing", runs[-1].end, duration, runs[-1]))

    return [
        DrumGap(
            start=start,
            end=end,
            bars=(end - start) / bar,
            kind=kind,
            structural=end - start >= STRUCTURAL_GAP_S,
            decaying=prev is not None and _decays(prev.end, end, drums.silences),
        )
        for kind, start, end, prev in spans
    ]


def _decays(last_onset: float, gap_end: float, silences: list[tuple[float, float]]) -> bool:
    following = [s for s, _ in silences if last_onset - _EDGE_TOLERANCE_S <= s < gap_end]
    return bool(following) and min(following) - last_onset > DECAY_S


def anchor_starts(gaps: list[DrumGap]) -> list[float]:
    """Run starts that follow a structural gap: where bar 1 is re-anchored."""
    return [g.end for g in gaps if g.structural and g.kind != "trailing"]


def has_mid_structural_gap(gaps: list[DrumGap]) -> bool:
    return any(g.kind == "mid" and g.structural for g in gaps)


def run_coverage(runs: list[DrumRun], start: float, end: float) -> float:
    """Fraction of [start, end) covered by drum runs."""
    if end <= start:
        return 0.0
    covered = sum(max(0.0, min(end, r.end) - max(start, r.start)) for r in runs)
    return covered / (end - start)
```

Note `run_coverage(runs, 50, 70)`: run 20–59.5 covers 50–59.5 = 9.5 s of 20 s.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_drums.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/audio/drums.py tests/test_drums.py
git commit -m "Add drum runs, gaps and anchor detection" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Silences in `analyze_stems`; cache version bump

**Files:**
- Modify: `src/xlights_mcp/audio/analyzer.py` (`analyze_stems`, ~line 190–215)
- Modify: `src/xlights_mcp/audio/cache.py:21`
- Modify: `tests/test_analysis_cache.py`

- [ ] **Step 1: Write the failing cache test** — append to `tests/test_analysis_cache.py`:

```python
def test_cache_ignores_entries_written_by_the_previous_version(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from xlights_mcp.audio import cache
    from xlights_mcp.audio.analyzer import SongAnalysis

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(cache, "ANALYSIS_VERSION", 1)
    cache.save_cached(SongAnalysis(file_path=str(click_track), file_name="click.wav"), click_track, cache_dir)
    monkeypatch.undo()

    assert cache.load_cached(click_track, cache_dir) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_analysis_cache.py::test_cache_ignores_entries_written_by_the_previous_version -v`
Expected: FAIL — `assert SongAnalysis(...) is None`

- [ ] **Step 3: Bump the version** in `cache.py`: `ANALYSIS_VERSION = 2`

- [ ] **Step 4: Compute silences in `analyze_stems`.** Add `from xlights_mcp.audio.drums import find_silences` to analyzer.py imports. In the loop, after `normalized_rms` is computed, pass silences into `StemOnsets`:

```python
            results[name] = StemOnsets(
                name=name,
                onset_times=onset_times,
                energy=normalized_rms,
                energy_times=rms_times,
                mean_energy=mean_energy,
                silences=find_silences(
                    np.asarray(normalized_rms), np.asarray(rms_times), end=len(y) / loaded_sr
                ),
            )
```

- [ ] **Step 5: Run the file**

Run: `.venv/Scripts/python -m pytest tests/test_analysis_cache.py -v`
Expected: all pass (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/xlights_mcp/audio/analyzer.py src/xlights_mcp/audio/cache.py tests/test_analysis_cache.py
git commit -m "Record per-stem silences and invalidate v1 analysis cache" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Beat snapping and downbeat re-anchoring (pure functions)

**Files:**
- Modify: `src/xlights_mcp/audio/beats.py`
- Create: `tests/test_beat_grid.py`

- [ ] **Step 1: Write failing tests** in `tests/test_beat_grid.py`:

```python
"""Tests for snapping the beat grid to drum onsets and re-anchoring bar 1."""

from __future__ import annotations

import numpy as np
import pytest

from xlights_mcp.audio.beats import anchor_downbeats, snap_beats


def test_snap_moves_a_late_grid_onto_drum_onsets():
    onsets = np.arange(0, 10, 0.5).tolist()
    late = [t + 0.045 for t in onsets]

    snapped = snap_beats(late, onsets)

    assert snapped == pytest.approx(onsets, abs=1e-3)


def test_snap_leaves_beats_with_no_onset_within_60ms():
    snapped = snap_beats([1.0, 2.0], [1.1, 2.03])

    assert snapped == [1.0, 2.03]


def test_snap_with_no_onsets_returns_grid_unchanged():
    assert snap_beats([1.0, 2.0], []) == [1.0, 2.0]


def test_anchors_become_downbeats_and_count_restarts_at_each():
    beats = np.arange(0, 40, 0.5).tolist()  # 80 beats
    anchors = [beats[10], beats[45]]  # beat 3 and beat 2 of a count from 0

    downbeats = anchor_downbeats(beats, anchors)

    expected_idx = [2, 6] + list(range(10, 45, 4)) + list(range(45, 80, 4))
    assert downbeats == [beats[i] for i in expected_idx]


def test_anchor_nearest_beat_is_used_when_anchor_is_between_beats():
    beats = np.arange(0, 10, 0.5).tolist()

    downbeats = anchor_downbeats(beats, [3.02])

    assert downbeats[0:3] == [1.0, 3.0, 5.0]
```

Check the last test: anchor 3.02 → nearest beat index 6 (3.0); backwards 6→2 (1.0); forward 6, 10 (5.0), …

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_beat_grid.py -v`
Expected: FAIL — `ImportError: cannot import name 'anchor_downbeats'`

- [ ] **Step 3: Implement** — add to `beats.py` (below `BeatMap`), and add `from xlights_mcp.audio.drums import BEATS_PER_BAR` to imports:

```python
SNAP_TOLERANCE_S = 0.060


def snap_beats(beats: list[float], onsets: list[float], tol: float = SNAP_TOLERANCE_S) -> list[float]:
    """Move each beat to the nearest onset within tol; beats with none in range stay put."""
    if not onsets:
        return list(beats)
    arr = np.sort(np.asarray(onsets, dtype=float))
    snapped = []
    for b in beats:
        i = int(np.searchsorted(arr, b))
        candidates = arr[max(i - 1, 0) : i + 1]
        nearest = float(candidates[np.argmin(np.abs(candidates - b))])
        snapped.append(nearest if abs(nearest - b) <= tol else b)
    return snapped


def anchor_downbeats(
    beats: list[float], anchors: list[float], beats_per_bar: int = BEATS_PER_BAR
) -> list[float]:
    """Downbeats counted from each anchor's nearest beat until the next anchor.

    Beats before the first anchor are counted backwards from it. The partial bar
    left where one count meets the next anchor is intentional: drops are placed
    against the phrase, not the previous bar count.
    """
    grid = np.asarray(beats, dtype=float)
    starts = sorted({int(np.argmin(np.abs(grid - a))) for a in anchors})
    idx = set(range(starts[0], -1, -beats_per_bar))
    for k, start in enumerate(starts):
        stop = starts[k + 1] if k + 1 < len(starts) else len(beats)
        idx.update(range(start, stop, beats_per_bar))
    return [beats[i] for i in sorted(idx)]
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_beat_grid.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/audio/beats.py tests/test_beat_grid.py
git commit -m "Add beat snapping and downbeat re-anchoring" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `detect_beats` with madmom base grid and drum alignment

**Files:**
- Modify: `src/xlights_mcp/audio/beats.py` (`BeatMap`, `detect_beats`, replace `_try_madmom_downbeats`)
- Modify: `tests/test_beat_grid.py`

- [ ] **Step 1: Append failing tests** to `tests/test_beat_grid.py`:

```python
from pathlib import Path

from drum_fixtures import make_drum_stem

from xlights_mcp.audio import beats as beats_module
from xlights_mcp.audio.beats import detect_beats


@pytest.fixture
def librosa_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _path: None)


def test_detect_beats_without_drums_is_not_drum_aligned(click_track: Path, librosa_only):
    result = detect_beats(click_track)

    assert result.beat_source == "librosa"
    assert result.drum_aligned is False
    assert result.tempo == pytest.approx(120, rel=0.1)


def test_detect_beats_snaps_to_drum_onsets(click_track: Path, librosa_only):
    # librosa places this click track's beats ~10-30 ms late (0.51, 1.02, 1.53, 2.02, 2.53)
    drums = make_drum_stem([(0, 3)], duration=3.0)

    result = detect_beats(click_track, drums=drums)

    assert result.drum_aligned is True
    assert result.beat_times == pytest.approx([0.5, 1.0, 1.5, 2.0, 2.5], abs=1e-6)
    # Drums from the start and no structural gap: no anchor, base every-4th downbeats kept
    assert result.downbeat_times == pytest.approx([0.5, 2.5], abs=1e-6)


def test_isolated_hit_in_a_gap_does_not_reset_bar_phase(click_track: Path, monkeypatch):
    grid = np.arange(0, 40, 0.5).tolist()
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: (grid, list(range(0, 80, 4))))
    monkeypatch.setattr(beats_module.librosa, "get_duration", lambda **_k: 40.0)
    # runs 0-9.5 and 21-39.5; a lone hit at 15.5 (beat 31) sits in the gap
    drums = make_drum_stem([(0, 10), (15.5, 16), (21, 40)], duration=40.0)

    result = detect_beats(click_track, drums=drums)

    # anchor at 21.0 (beat 42, i.e. 42 % 4 == 2) re-phases the whole song
    assert result.downbeat_times == [grid[i] for i in range(2, 80, 4)]
    assert 15.5 not in result.downbeat_times


def test_detect_beats_uses_madmom_grid_when_available(click_track: Path, monkeypatch):
    monkeypatch.setattr(beats_module, "_madmom_grid", lambda _p: ([0.0, 0.5, 1.0, 1.5, 2.0, 2.5], [1, 5]))

    result = detect_beats(click_track)

    assert result.beat_source == "madmom"
    assert result.downbeat_times == [0.5, 2.5]
    assert result.tempo == pytest.approx(120)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_beat_grid.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_madmom_grid'`

- [ ] **Step 3: Implement.** In `beats.py`:

Add fields to `BeatMap` (after `beats_per_bar`):

```python
    beat_source: Literal["madmom", "librosa"] = "librosa"
    drum_aligned: bool = False
```

Add imports: `from typing import Literal`, and `from xlights_mcp.audio.drums import BEATS_PER_BAR, anchor_starts, drum_gaps, drum_runs` (replace the Task 5 import), and `from xlights_mcp.audio.stems_model import StemOnsets`.

Replace `detect_beats` and `_try_madmom_downbeats` entirely with:

```python
def detect_beats(audio_path: Path, sr: int = 22050, drums: StemOnsets | None = None) -> BeatMap:
    """Detect beats, downbeats and mixdown onsets.

    Base grid from madmom when installed, else librosa. With a drum stem the grid
    is snapped to drum onsets and bar 1 is re-anchored at each run that follows a
    structural drum gap (see docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md).
    """
    logger.info(f"Analyzing beats: {audio_path}")
    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr).tolist()

    grid = _madmom_grid(audio_path)
    if grid is not None:
        beat_times, downbeat_idx = grid
        beat_source = "madmom"
    else:
        _, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        downbeat_idx = list(range(0, len(beat_times), BEATS_PER_BAR))
        beat_source = "librosa"

    tempo = 60.0 / float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 0.0

    drum_aligned = False
    if drums is not None and drums.onset_times and beat_times:
        beat_times = snap_beats(beat_times, drums.onset_times)
        drum_aligned = True
    downbeat_times = [beat_times[i] for i in downbeat_idx]

    if drum_aligned and tempo > 0:
        period = 60.0 / tempo
        runs = drum_runs(drums, beat_period=period, duration=duration)
        anchors = anchor_starts(drum_gaps(runs, drums, duration=duration, beat_period=period))
        if anchors:
            downbeat_times = anchor_downbeats(beat_times, anchors)

    logger.info(
        f"Detected: tempo={tempo:.1f} BPM ({beat_source}), {len(beat_times)} beats, "
        f"{len(downbeat_times)} downbeats, {len(onset_times)} onsets, drum_aligned={drum_aligned}"
    )
    return BeatMap(
        tempo=tempo,
        beat_times=beat_times,
        downbeat_times=downbeat_times,
        onset_times=onset_times,
        beat_source=beat_source,
        drum_aligned=drum_aligned,
    )


def _madmom_grid(audio_path: Path) -> tuple[list[float], list[int]] | None:
    """Beat times and indices of madmom's bar-position-1 beats, or None if unavailable."""
    try:
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor
    except ImportError:
        logger.debug("madmom not installed, using librosa beat tracking")
        return None
    try:
        activations = RNNDownBeatProcessor()(str(audio_path))
        rows = DBNDownBeatTrackingProcessor(beats_per_bar=[BEATS_PER_BAR], fps=100)(activations)
    except Exception as e:  # noqa: BLE001 - any madmom failure falls back to librosa
        logger.warning(f"madmom beat tracking failed, using librosa: {e}")
        return None
    if len(rows) == 0:
        return None
    return [float(r[0]) for r in rows], [i for i, r in enumerate(rows) if int(r[1]) == 1]
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_beat_grid.py -v`
Expected: 9 passed

- [ ] **Step 5: Full suite** (detect_beats is used everywhere)

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/xlights_mcp/audio/beats.py tests/test_beat_grid.py
git commit -m "Lock beat grid to drum onsets, with madmom as optional base grid" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: EDM section labelling

**Files:**
- Create: `src/xlights_mcp/audio/edm_structure.py`
- Create: `tests/test_edm_structure.py`

- [ ] **Step 1: Write failing tests** in `tests/test_edm_structure.py`:

```python
"""Tests for drum-derived (EDM) section labelling."""

from __future__ import annotations

import numpy as np
from drum_fixtures import make_drum_stem

from xlights_mcp.audio.drums import drum_gaps, drum_runs
from xlights_mcp.audio.edm_structure import label_edm_sections

PERIOD = 0.5  # 120 BPM, 2 s bars


def _label(runs_spec, duration, novelty=(), decay_s=0.0):
    stem = make_drum_stem(runs_spec, duration, decay_s=decay_s)
    runs = drum_runs(stem, beat_period=PERIOD, duration=duration)
    gaps = drum_gaps(runs, stem, duration=duration, beat_period=PERIOD)
    downbeats = np.arange(0, duration, 2.0).tolist()
    sections = label_edm_sections(
        runs, gaps, list(novelty), downbeats, duration, PERIOD, energy_at=lambda a, b: 1.0
    )
    return sections


def _summary(sections):
    return [(s.label, s.start_time, s.end_time) for s in sections]


def test_intro_drop_breakdown_drop_outro():
    sections = _label([(20, 60), (80, 120)], 130, decay_s=2.0)

    assert _summary(sections) == [
        ("intro", 0.0, 20.0),
        ("drop", 20.0, 60.0),
        ("breakdown", 60.0, 80.0),
        ("drop", 80.0, 120.0),
        ("outro", 120.0, 130.0),
    ]
    assert sections[2].drums == "decaying"
    assert sections[1].drums == "present"
    assert all(s.structure_source == "stems" and s.confidence == 0.9 for s in sections)


def test_novelty_inside_long_gap_starts_a_build():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[72.0])

    assert [s.label for s in sections] == ["intro", "drop", "breakdown", "build", "drop", "outro"]
    assert sections[3].start_time == 72.0


def test_only_the_last_novelty_boundary_in_a_gap_starts_the_build():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[66.0, 72.0])

    assert [s.label for s in sections] == [
        "intro", "drop", "breakdown", "breakdown", "build", "drop", "outro",
    ]


def test_short_mid_gap_is_a_build_and_drums_from_start_is_intro():
    sections = _label([(0, 40), (48, 80)], 80)

    assert _summary(sections) == [
        ("intro", 0.0, 40.0),
        ("build", 40.0, 48.0),
        ("drop", 48.0, 80.0),
    ]
    assert sections[0].drums == "present"


def test_drums_present_sections_inherit_the_previous_label():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[40.0])

    assert [s.label for s in sections][:3] == ["intro", "drop", "drop"]


def test_novelty_boundary_near_a_drum_boundary_is_dropped():
    sections = _label([(20, 60), (80, 120)], 130, novelty=[21.0])

    assert [s.start_time for s in sections] == [0.0, 20.0, 60.0, 80.0, 120.0]


def test_short_sections_merge_into_predecessor_and_first_into_successor():
    from xlights_mcp.audio.edm_structure import _merge_short

    # [0,1) is first, so it merges forward; [5,5.5) then merges back into its predecessor
    assert _merge_short([0.0, 1.0, 5.0, 5.5, 10.0], 2.0) == [0.0, 5.5, 10.0]
    assert _merge_short([0.0, 10.0], 2.0) == [0.0, 10.0]
```

(Boundaries snapped to a regular 2 s downbeat grid can't produce sections under a bar, so this is tested directly; short sections occur at anchors, where the bar count restarts mid-bar.)

Why the numbers work: runs are 20–59.5 and 80–119.5 (onsets every 0.5 s); the run-end at 59.5 snaps to downbeat 60; gaps are measured 59.5→80 (10.25 bars → breakdown) and 39.5→48 (4.25 bars → build).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_edm_structure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xlights_mcp.audio.edm_structure'`

- [ ] **Step 3: Implement `edm_structure.py`:**

```python
"""Section labelling for tracks with a structural mid-song drum gap.

Implements the labels table in docs/superpowers/specs/2026-09-22-stem-aware-analysis-design.md.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise

import numpy as np

from xlights_mcp.audio.drums import BEATS_PER_BAR, DrumGap, DrumRun, anchor_starts
from xlights_mcp.audio.sections import SongSection

NOVELTY_MERGE_S = 2.0
BUILD_MAX_BARS = 8
EDM_CONFIDENCE = 0.9


def label_edm_sections(
    runs: list[DrumRun],
    gaps: list[DrumGap],
    novelty_times: list[float],
    downbeat_times: list[float],
    duration: float,
    beat_period: float,
    energy_at: Callable[[float, float], float],
) -> list[SongSection]:
    downbeats = np.asarray(downbeat_times, dtype=float)
    structural = [g for g in gaps if g.structural]

    drum_bounds: list[float] = []
    for g in structural:
        if g.kind != "leading":
            drum_bounds.append(g.start)
        if g.kind != "trailing":
            drum_bounds.append(g.end)
    novelty = [n for n in novelty_times if all(abs(n - d) >= NOVELTY_MERGE_S for d in drum_bounds)]

    inner = sorted({_snap(t, downbeats) for t in drum_bounds + novelty})
    points = [0.0] + [p for p in inner if 0.0 < p < duration] + [float(duration)]
    points = _merge_short(points, BEATS_PER_BAR * beat_period)

    anchors = {_snap(a, downbeats) for a in anchor_starts(gaps)}
    seen_gaps: set[int] = set()
    labelled: list[tuple[str, str, float, float]] = []
    prev_label: str | None = None
    for start, end in pairwise(points):
        mid = (start + end) / 2
        gap = next((g for g in structural if g.start <= mid < g.end), None)
        if gap is not None:
            first_in_gap = id(gap) not in seen_gaps
            seen_gaps.add(id(gap))
            fade = "decaying" if first_in_gap and gap.decaying else "absent"
            label, drums = _gap_label(gap, start, novelty, downbeats, fade)
        elif start in anchors:
            label, drums = "drop", "present"
        elif prev_label is None:
            label, drums = "intro", "present"
        else:
            label, drums = prev_label, "present"
        labelled.append((label, drums, start, end))
        prev_label = label

    energies = [energy_at(s, e) for _, _, s, e in labelled]
    peak = max(energies, default=0.0) or 1.0
    return [
        SongSection(
            label=label,
            start_time=start,
            end_time=end,
            energy_level=energy / peak,
            confidence=EDM_CONFIDENCE,
            structure_source="stems",
            drums=drums,
        )
        for (label, drums, start, end), energy in zip(labelled, energies)
    ]


def _gap_label(
    gap: DrumGap, start: float, novelty: list[float], downbeats: np.ndarray, fade: str
) -> tuple[str, str]:
    if gap.kind == "leading":
        return "intro", "absent"
    if gap.kind == "trailing":
        return "outro", fade
    if gap.bars <= BUILD_MAX_BARS:
        return "build", fade
    inside = [n for n in novelty if gap.start < n < gap.end]
    if inside and start >= _snap(max(inside), downbeats):
        return "build", "absent"
    return "breakdown", fade


def _snap(t: float, downbeats: np.ndarray) -> float:
    if downbeats.size == 0:
        return float(t)
    return float(downbeats[np.argmin(np.abs(downbeats - t))])


def _merge_short(points: list[float], min_len: float) -> list[float]:
    """Drop boundaries until every section is at least min_len long.

    A short section merges into its predecessor; the first section merges into its successor.
    """
    pts = list(points)
    while len(pts) > 2:
        short = next((k for k in range(len(pts) - 1) if pts[k + 1] - pts[k] < min_len - 1e-6), None)
        if short is None:
            break
        del pts[1 if short == 0 else short]
    return pts
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_edm_structure.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/audio/edm_structure.py tests/test_edm_structure.py
git commit -m "Label sections from drum gaps: intro, build, drop, breakdown, outro" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `detect_structure` mode selection

**Files:**
- Modify: `src/xlights_mcp/audio/structure.py` (`detect_structure`, lines ~36–106)
- Create: `tests/test_structure_modes.py`

- [ ] **Step 1: Write failing tests** in `tests/test_structure_modes.py`:

```python
"""detect_structure picks EDM labelling, stem-annotated fallback, or mixdown-only."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from drum_fixtures import make_drum_stem

from xlights_mcp.audio import structure
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.audio.stems_model import StemOnsets
from xlights_mcp.audio.structure import detect_structure


def _beats(duration: float) -> BeatMap:
    return BeatMap(
        tempo=120.0,
        beat_times=np.arange(0, duration, 0.5).tolist(),
        downbeat_times=np.arange(0, duration, 2.0).tolist(),
    )


@pytest.fixture
def two_mixdown_sections(monkeypatch: pytest.MonkeyPatch):
    # The 3 s click track yields no sections from the real labeller (all under 1 s),
    # so stub the mixdown path to test the annotation around it.
    monkeypatch.setattr(
        structure,
        "_mixdown_sections",
        lambda *_a, **_k: [
            SongSection(label="verse", start_time=0.0, end_time=1.5),
            SongSection(label="chorus", start_time=1.5, end_time=3.0),
        ],
    )


def test_without_stems_structure_is_mixdown(click_track: Path, two_mixdown_sections):
    sections = detect_structure(click_track)

    assert [s.label for s in sections] == ["verse", "chorus"]
    assert all(s.structure_source == "mixdown" and s.drums is None for s in sections)


def test_steady_drums_fall_back_to_existing_labeller(click_track: Path, two_mixdown_sections):
    drums = make_drum_stem([(0, 3)], duration=3.0)  # one run 0-2.5 s, no mid gap

    sections = detect_structure(click_track, drums=drums, beats=_beats(3.0))

    assert [s.label for s in sections] == ["verse", "chorus"]
    assert all(s.structure_source == "stems" for s in sections)
    # [1.5, 3.0) is 1.0/1.5 covered by the run -> present
    assert [s.drums for s in sections] == ["present", "present"]


def test_drum_stem_without_onsets_marks_every_section_absent(click_track: Path, two_mixdown_sections):
    drums = StemOnsets(name="drums", silences=[(0.0, 3.0)])

    sections = detect_structure(click_track, drums=drums, beats=_beats(3.0))

    assert all(s.structure_source == "stems" and s.drums == "absent" for s in sections)


def test_mid_structural_gap_switches_to_edm_labels(click_track: Path, monkeypatch):
    drums = make_drum_stem([(20, 60), (80, 120)], duration=130)
    edm = [SongSection(label="drop", start_time=0.0, end_time=130.0, structure_source="stems")]
    captured = {}

    def fake_label(runs, gaps, novelty, downbeats, duration, beat_period, energy_at):
        captured["duration"] = duration
        return edm

    monkeypatch.setattr(structure, "label_edm_sections", fake_label)
    monkeypatch.setattr(structure.librosa, "get_duration", lambda **_k: 130.0)

    assert detect_structure(click_track, drums=drums, beats=_beats(130.0)) == edm
    assert captured["duration"] == 130.0


def test_short_drum_stop_keeps_the_existing_labeller(click_track: Path, two_mixdown_sections, monkeypatch):
    drums = make_drum_stem([(0, 40), (42, 60)], duration=60)  # 2.5 s stop: not structural
    monkeypatch.setattr(structure.librosa, "get_duration", lambda **_k: 60.0)

    sections = detect_structure(click_track, drums=drums, beats=_beats(60.0))

    assert [s.label for s in sections] == ["verse", "chorus"]
    assert all(s.structure_source == "stems" for s in sections)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_structure_modes.py -v`
Expected: FAIL — `TypeError: detect_structure() got an unexpected keyword argument 'drums'`

- [ ] **Step 3: Implement.** Imports to add in structure.py:

```python
from xlights_mcp.audio.drums import (
    drum_gaps,
    drum_runs,
    has_mid_structural_gap,
    merge_short_stops,
    run_coverage,
)
from xlights_mcp.audio.edm_structure import label_edm_sections
from xlights_mcp.audio.stems_model import StemOnsets
```

and under `if TYPE_CHECKING:` (add `from typing import TYPE_CHECKING`): `from xlights_mcp.audio.beats import BeatMap`.

Replace the whole of `detect_structure` (from `def detect_structure` through its `return sections`) with the two functions below. The feature/novelty/fallback lines are the existing code; the boundary cleanup, per-section energy and labelling move into `_mixdown_sections`.

```python
def detect_structure(
    audio_path: Path,
    sr: int = 22050,
    drums: StemOnsets | None = None,
    beats: BeatMap | None = None,
) -> list[SongSection]:
    """Detect song sections.

    With a drum stem and at least one structural mid-song drum gap, sections are
    labelled from drum presence (intro/build/drop/breakdown/outro). Otherwise the
    MFCC/chroma novelty + energy labeller is used, annotated with drum presence
    when a drum stem exists.
    """
    logger.info(f"Analyzing song structure: {audio_path}")
    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    features = np.vstack([mfcc, chroma])
    rec = librosa.segment.recurrence_matrix(features, mode="affinity", sym=True, bandwidth=1.0)

    kernel_size = max(8, min(64, features.shape[1] // 20))
    novelty = _compute_novelty(rec, kernel_size=kernel_size)
    boundary_frames = _detect_boundaries(novelty, min_section_frames=15, peak_threshold=0.1)
    boundary_times = librosa.frames_to_time(boundary_frames, sr=sr).tolist()

    min_sections = max(4, int(duration / 30))  # at least 1 section per 30s
    if len(boundary_times) < min_sections:
        logger.info(f"Novelty found only {len(boundary_times)} boundaries, using energy-based fallback")
        boundary_times = _energy_based_segmentation(y, sr, duration, min_sections)

    novelty_times = [t for t in boundary_times if 0.0 < t < duration]
    rms = librosa.feature.rms(y=y)[0]
    rms_times = librosa.times_like(rms, sr=sr)

    def energy_at(start: float, end: float) -> float:
        mask = (rms_times >= start) & (rms_times < end)
        return float(np.mean(rms[mask])) if np.any(mask) else 0.0

    presence = None  # drum runs merged across short stops; set when a drum stem is usable
    if drums is not None and beats is not None and beats.tempo > 0:
        beat_period = 60.0 / beats.tempo
        runs = drum_runs(drums, beat_period=beat_period, duration=duration)
        gaps = drum_gaps(runs, drums, duration=duration, beat_period=beat_period)
        presence = merge_short_stops(runs, gaps)
        if has_mid_structural_gap(gaps):
            sections = label_edm_sections(
                runs, gaps, novelty_times, beats.downbeat_times, duration, beat_period, energy_at
            )
            logger.info(f"Detected {len(sections)} sections from drum stem: {[s.label for s in sections]}")
            return sections

    sections = _mixdown_sections(list(boundary_times), duration, energy_at, rec, features, sr)
    if presence is not None:
        for s in sections:
            s.structure_source = "stems"
            s.drums = "present" if run_coverage(presence, s.start_time, s.end_time) > 0.5 else "absent"
    logger.info(f"Detected {len(sections)} sections: {[s.label for s in sections]}")
    return sections


def _mixdown_sections(
    boundary_times: list[float],
    duration: float,
    energy_at: Callable[[float, float], float],
    rec: np.ndarray,
    features: np.ndarray,
    sr: int,
) -> list[SongSection]:
    """Existing boundary cleanup, per-section energy and heuristic labelling."""
    if not boundary_times or boundary_times[0] > 2.0:
        boundary_times.insert(0, 0.0)
    if boundary_times[-1] < duration - 2.0:
        boundary_times.append(duration)
    boundary_times = sorted(set(round(t, 2) for t in boundary_times))

    sections = []
    for start, end in pairwise(boundary_times):
        if end - start < 1.0:
            continue
        sections.append(
            SongSection(label="unknown", start_time=start, end_time=end, energy_level=energy_at(start, end))
        )
    return _label_sections(sections, duration, rec, features, sr)
```

Add `from collections.abc import Callable` and `from itertools import pairwise` to imports. `_compute_novelty`, `_detect_boundaries`, `_energy_based_segmentation`, `_label_sections` and `_refine_labels_by_repetition` stay as they are.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_structure_modes.py -v`
Expected: 5 passed

- [ ] **Step 5: Full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/xlights_mcp/audio/structure.py tests/test_structure_modes.py
git commit -m "Select EDM or fallback section labelling from the drum stem" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Run stems before beats and structure

**Files:**
- Modify: `src/xlights_mcp/audio/analyzer.py` (`full_analysis`, ~lines 121–145)
- Create: `tests/test_pipeline_order.py`

- [ ] **Step 1: Write the failing test** in `tests/test_pipeline_order.py`:

```python
"""full_analysis feeds the drum stem into beat and structure detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from xlights_mcp.audio import analyzer
from xlights_mcp.audio.analyzer import StemAnalysis, StemOnsets, full_analysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.separator import StemPaths
from xlights_mcp.config import AudioConfig


def test_drum_stem_reaches_beats_and_structure(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    drums = StemOnsets(name="drums", onset_times=[0.0, 0.5])
    calls: list[tuple[str, object]] = []
    beat_map = BeatMap(tempo=120.0)

    monkeypatch.setattr(analyzer, "separate_stems", lambda _p: StemPaths(available=True))
    monkeypatch.setattr(
        analyzer, "analyze_stems", lambda _s, sr: StemAnalysis(available=True, stems={"drums": drums})
    )

    def fake_beats(path, sr, drums=None):
        calls.append(("beats", drums))
        return beat_map

    def fake_structure(path, sr, drums=None, beats=None):
        calls.append(("structure", (drums, beats)))
        return []

    monkeypatch.setattr(analyzer, "detect_beats", fake_beats)
    monkeypatch.setattr(analyzer, "detect_structure", fake_structure)

    full_analysis(click_track, AudioConfig(cache_dir=tmp_path / "cache"))

    assert calls == [("beats", drums), ("structure", (drums, beat_map))]


def test_without_stems_beats_and_structure_get_none(
    click_track: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    seen = {}
    monkeypatch.setattr(analyzer, "separate_stems", lambda _p: StemPaths(available=False))
    monkeypatch.setattr(
        analyzer, "detect_beats", lambda path, sr, drums=None: seen.setdefault("beats", drums) or BeatMap()
    )
    monkeypatch.setattr(
        analyzer, "detect_structure", lambda path, sr, drums=None, beats=None: seen.setdefault("structure", drums) or []
    )

    full_analysis(click_track, AudioConfig(cache_dir=tmp_path / "cache"))

    assert seen == {"beats": None, "structure": None}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_pipeline_order.py -v`
Expected: `test_drum_stem_reaches_beats_and_structure` FAILS (`drums` is never passed today); `test_without_stems_beats_and_structure_get_none` already passes — it guards the no-stems path.

- [ ] **Step 3: Implement.** In `full_analysis`, replace the block from `report(0, "Detecting beats and tempo")` through the stem `try/except` with:

```python
    report(0, "Analyzing spectrum and energy")
    spectrum = analyze_spectrum(audio_path, sr=sr)

    report(1, "Separating stems")
    stems = StemPaths()
    stem_analysis = StemAnalysis()
    try:
        stems = separate_stems(audio_path)
        if stems.available:
            report(2, "Analyzing stems")
            stem_analysis = analyze_stems(stems, sr=sr)
    except Exception as e:
        logger.info(f"Stem analysis unavailable: {e}")

    drums = stem_analysis.stems.get("drums") if stem_analysis.available else None
    report(3, "Detecting beats and tempo")
    beats = detect_beats(audio_path, sr=sr, drums=drums)
    report(4, "Detecting song structure")
    sections = detect_structure(audio_path, sr=sr, drums=drums, beats=beats)
```

Leave the `SongAnalysis(...)` construction and everything after it unchanged.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_pipeline_order.py tests/test_analysis_cache.py -v`
Expected: all pass (stage messages are still monotonic and still mention beat/spectrum/structure)

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/audio/analyzer.py tests/test_pipeline_order.py
git commit -m "Analyze stems before beats and structure so both can use the drum stem" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Engine understands the new labels

**Files:**
- Modify: `src/xlights_mcp/sequencer/engine.py` (after `SECTION_TYPE_CONFIG`, ~line 306)
- Create: `tests/test_engine_labels.py`

- [ ] **Step 1: Write the failing test:**

```python
"""Every section label the analyzer can emit has sequencing config."""

from xlights_mcp.audio.sections import SECTION_LABELS
from xlights_mcp.sequencer.engine import SECTION_TYPE_CONFIG


def test_every_section_label_has_engine_config():
    assert set(SECTION_LABELS) <= set(SECTION_TYPE_CONFIG)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_engine_labels.py -v`
Expected: FAIL — missing `build`, `drop`, `breakdown`

- [ ] **Step 3: Implement** — directly below the `SECTION_TYPE_CONFIG` dict:

```python
# Drum-derived labels reuse the closest existing behaviour until they get their own recipes.
SECTION_TYPE_CONFIG["build"] = SECTION_TYPE_CONFIG["transition"]
SECTION_TYPE_CONFIG["drop"] = SECTION_TYPE_CONFIG["chorus"]
SECTION_TYPE_CONFIG["breakdown"] = SECTION_TYPE_CONFIG["bridge"]
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_engine_labels.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/sequencer/engine.py tests/test_engine_labels.py
git commit -m "Map build/drop/breakdown onto existing sequencing config" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Stem summary and stem-event payloads (pure functions)

**Files:**
- Create: `src/xlights_mcp/audio/stem_events.py`
- Create: `tests/test_stem_events.py`

- [ ] **Step 1: Write failing tests** in `tests/test_stem_events.py`:

```python
"""Tests for LLM-sized stem payloads."""

from __future__ import annotations

import numpy as np
import pytest
from drum_fixtures import make_drum_stem

from xlights_mcp.audio.analyzer import SongAnalysis, StemAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.stem_events import stem_events, stems_summary


@pytest.fixture
def analysis() -> SongAnalysis:
    return SongAnalysis(
        file_path="song.mp3",
        file_name="song.mp3",
        duration_seconds=20.0,
        beats=BeatMap(
            tempo=120.0,
            beat_times=np.arange(0, 20, 0.5).tolist(),
            downbeat_times=np.arange(0, 20, 2.0).tolist(),
        ),
        stem_analysis=StemAnalysis(
            available=True, stems={"drums": make_drum_stem([(0, 8), (12, 20)], duration=20.0)}
        ),
    )


def test_summary_reports_counts_energy_and_silences_in_ms(analysis):
    summary = stems_summary(analysis)

    drums = summary["drums"]
    assert drums["onsets"] == 32
    assert isinstance(drums["mean_energy"], float)
    assert len(drums["silences_ms"]) == 1
    start, end = drums["silences_ms"][0]
    assert isinstance(start, int) and 7700 < start < 7900 and 11900 < end < 12100


def test_summary_is_none_without_stems(analysis):
    analysis.stem_analysis = StemAnalysis()

    assert stems_summary(analysis) is None


def test_onsets_are_windowed_ms(analysis):
    payload = stem_events(analysis, "drums", "onsets", start_ms=1000, end_ms=3000)

    assert payload["events_ms"] == [1000, 1500, 2000, 2500]
    assert payload["count"] == 4
    assert "truncated" not in payload


def test_onsets_truncate_with_resume_point(analysis):
    payload = stem_events(analysis, "drums", "onsets", max_events=3)

    assert payload["events_ms"] == [0, 500, 1000]
    assert payload["truncated"] is True
    assert payload["next_start_ms"] == 1500


def test_energy_one_point_per_beat_in_window(analysis):
    payload = stem_events(analysis, "drums", "energy", start_ms=0, end_ms=4000)

    assert [p["t_ms"] for p in payload["points"]] == list(range(0, 4000, 500))
    assert all(p["energy"] == pytest.approx(1.0, abs=0.01) for p in payload["points"])


def test_energy_bar_resolution_and_truncation(analysis):
    payload = stem_events(analysis, "drums", "energy", resolution="bar", max_events=2)

    assert [p["t_ms"] for p in payload["points"]] == [0, 2000]
    assert payload["next_start_ms"] == 4000


def test_silences_are_clipped_to_window(analysis):
    payload = stem_events(analysis, "drums", "silences", start_ms=10000)

    assert payload["spans_ms"][0][0] == 10000


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (("kick", "onsets"), "drums"),
        (("drums", "hits"), "onsets"),
    ],
)
def test_invalid_stem_or_kind_lists_valid_values(analysis, args, needle):
    assert needle in stem_events(analysis, *args)["error"]


def test_invalid_resolution_errors(analysis):
    assert "beat" in stem_events(analysis, "drums", "energy", resolution="frame")["error"]


def test_missing_stems_errors_with_install_hint(analysis):
    analysis.stem_analysis = StemAnalysis()

    assert "separation" in stem_events(analysis, "drums", "onsets")["error"]
```

Why `drums["onsets"] == 32`: runs 0–8 and 12–20 with onsets every 0.5 s → 16 + 16.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_stem_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xlights_mcp.audio.stem_events'`

- [ ] **Step 3: Implement `stem_events.py`:**

```python
"""Turn cached stem analysis into compact, windowed payloads for MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from xlights_mcp.audio.analyzer import SongAnalysis

VALID_STEMS = ("drums", "bass", "vocals", "other")
VALID_KINDS = ("onsets", "energy", "silences")
VALID_RESOLUTIONS = ("beat", "bar")
STEMS_UNAVAILABLE = 'Stem analysis unavailable. Install with: uv pip install -e ".[separation]"'


def _ms(t: float) -> int:
    return round(t * 1000)


def stems_summary(analysis: SongAnalysis) -> dict[str, dict] | None:
    sa = analysis.stem_analysis
    if not sa.available:
        return None
    return {
        name: {
            "onsets": len(s.onset_times),
            "mean_energy": round(s.mean_energy, 2),
            "silences_ms": [[_ms(a), _ms(b)] for a, b in s.silences],
        }
        for name, s in sa.stems.items()
    }


def validate_stem_query(stem: str, kind: str, resolution: str) -> str | None:
    if stem not in VALID_STEMS:
        return f"Unknown stem '{stem}'. Valid: {', '.join(VALID_STEMS)}"
    if kind not in VALID_KINDS:
        return f"Unknown kind '{kind}'. Valid: {', '.join(VALID_KINDS)}"
    if resolution not in VALID_RESOLUTIONS:
        return f"Unknown resolution '{resolution}'. Valid: {', '.join(VALID_RESOLUTIONS)}"
    return None


def stem_events(
    analysis: SongAnalysis,
    stem: str,
    kind: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
    max_events: int = 500,
    resolution: str = "beat",
) -> dict[str, Any]:
    error = validate_stem_query(stem, kind, resolution)
    if error:
        return {"error": error}
    sa = analysis.stem_analysis
    if not sa.available or stem not in sa.stems:
        return {"error": STEMS_UNAVAILABLE}

    s = sa.stems[stem]
    lo = (start_ms or 0) / 1000
    hi = end_ms / 1000 if end_ms is not None else analysis.duration_seconds
    base: dict[str, Any] = {"stem": stem, "kind": kind}

    if kind == "onsets":
        events = [_ms(t) for t in s.onset_times if lo <= t < hi]
        base["count"] = len(events)
        return _truncate(base, "events_ms", events, max_events, key=lambda e: e)

    if kind == "silences":
        base["spans_ms"] = [[_ms(max(a, lo)), _ms(min(b, hi))] for a, b in s.silences if b > lo and a < hi]
        return base

    grid = analysis.beats.beat_times if resolution == "beat" else analysis.beats.downbeat_times
    edges = [*grid, analysis.duration_seconds]
    times = np.asarray(s.energy_times, dtype=float)
    energy = np.asarray(s.energy, dtype=float)
    points = []
    for a, b in pairwise(edges):
        if not lo <= a < hi:
            continue
        mask = (times >= a) & (times < b)
        value = float(energy[mask].mean()) if mask.any() else 0.0
        points.append({"t_ms": _ms(a), "energy": round(value, 3)})
    base["resolution"] = resolution
    return _truncate(base, "points", points, max_events, key=lambda p: p["t_ms"])


def _truncate(
    payload: dict[str, Any], field: str, items: list, max_events: int, key: Callable[[Any], int]
) -> dict[str, Any]:
    if len(items) > max_events:
        payload["truncated"] = True
        payload["next_start_ms"] = key(items[max_events])
        items = items[:max_events]
    payload[field] = items
    return payload
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_stem_events.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/xlights_mcp/audio/stem_events.py tests/test_stem_events.py
git commit -m "Add windowed stem summary and stem event payloads" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: MCP surface — `analyze_song` fields, `get_stem_events`, madmom preload

**Files:**
- Modify: `src/xlights_mcp/server.py` (`analyze_song` ~line 313; new tool after `get_energy_profile` ~line 401; `_preload_audio_stack` ~line 726)
- Modify: `tests/test_analyze_song_tool.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_analyze_song_tool.py`:

```python
import numpy as np
from drum_fixtures import make_drum_stem

from xlights_mcp.audio.analyzer import SongAnalysis, StemAnalysis
from xlights_mcp.audio.beats import BeatMap
from xlights_mcp.audio.cache import save_cached
from xlights_mcp.audio.sections import SongSection


def _cache_fake_analysis(path: Path, config: ServerConfig, with_stems: bool = True) -> None:
    analysis = SongAnalysis(
        file_path=str(path),
        file_name=path.name,
        duration_seconds=20.0,
        beats=BeatMap(
            tempo=120.0,
            beat_times=np.arange(0, 20, 0.5).tolist(),
            downbeat_times=np.arange(0, 20, 2.0).tolist(),
            beat_source="madmom",
            drum_aligned=with_stems,
        ),
        sections=[
            SongSection(label="drop", start_time=0.0, end_time=20.0, structure_source="stems", drums="present")
        ],
        stem_analysis=StemAnalysis(
            available=with_stems,
            stems={"drums": make_drum_stem([(0, 8), (12, 20)], duration=20.0)} if with_stems else {},
        ),
    )
    save_cached(analysis, path, config.audio.cache_dir)


async def test_analyze_song_reports_stem_summary_and_provenance(
    click_track: Path, isolated_config: ServerConfig
):
    _cache_fake_analysis(click_track, isolated_config)

    payload, _ = await _call_analyze(click_track)

    assert payload["beat_source"] == "madmom"
    assert payload["drum_aligned"] is True
    assert payload["structure_source"] == "stems"
    assert payload["stems"]["drums"]["onsets"] == 32
    assert payload["sections"][0]["drums"] == "present"


async def test_analyze_song_stems_null_without_separation(
    click_track: Path, isolated_config: ServerConfig
):
    _cache_fake_analysis(click_track, isolated_config, with_stems=False)

    payload, _ = await _call_analyze(click_track)

    assert payload["stems"] is None


async def test_get_stem_events_serves_windowed_onsets(click_track: Path, isolated_config: ServerConfig):
    _cache_fake_analysis(click_track, isolated_config)

    payload, _ = await _call(
        "get_stem_events",
        {"mp3_path": str(click_track), "stem": "drums", "kind": "onsets", "start_ms": 1000, "end_ms": 3000},
    )

    assert payload["events_ms"] == [1000, 1500, 2000, 2500]


async def test_get_stem_events_rejects_bad_kind_before_analysing(
    click_track: Path, isolated_config: ServerConfig, monkeypatch
):
    def boom(*_a, **_k):
        raise AssertionError("analysed despite invalid arguments")

    monkeypatch.setattr(server_module, "_analyze_in_thread", boom)

    payload, _ = await _call("get_stem_events", {"mp3_path": str(click_track), "stem": "drums", "kind": "hits"})

    assert "onsets" in payload["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_analyze_song_tool.py -v`
Expected: the 4 new tests FAIL (`KeyError: 'beat_source'`, unknown tool `get_stem_events`)

- [ ] **Step 3: Extend `analyze_song`'s return dict** — add after `"onset_count"`:

```python
        "beat_source": analysis.beats.beat_source,
        "drum_aligned": analysis.beats.drum_aligned,
        "structure_source": analysis.sections[0].structure_source if analysis.sections else "mixdown",
```

and replace `"stems_available": analysis.stem_analysis.available,` with:

```python
        "stems": stems_summary(analysis),
```

Add `from xlights_mcp.audio.stem_events import stems_summary` at the top of `analyze_song`'s body (server.py imports audio modules lazily inside tools — keep that pattern).

Check `tests/test_analyze_song_tool.py` and other tests for `stems_available` and update any assertion to use `payload["stems"]` instead:

Run: `grep -rn stems_available tests src`
Expected after the edit: no matches.

Also update the `analyze_song` docstring's last paragraph to: "Returns a compact summary; use get_beat_map / get_energy_profile / get_song_structure / get_stem_events for detailed data."

- [ ] **Step 4: Add the tool** after `get_energy_profile`:

```python
@mcp.tool()
async def get_stem_events(
    mp3_path: str,
    ctx: Context,
    stem: str,
    kind: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
    max_events: int = 500,
    resolution: str = "beat",
) -> dict:
    """Get per-stem events from source separation (drums, bass, vocals, other).

    kind="onsets": hit times in ms (e.g. drum hits, vocal phrase starts).
    kind="energy": stem loudness, one value per beat (resolution="beat") or bar ("bar").
    kind="silences": [start, end] ms spans where the stem is silent (drops, breakdowns, risers).
    Results are windowed by start_ms/end_ms and capped at max_events; when truncated, the
    response has truncated=true and next_start_ms to continue from.
    Served from the analysis cache when available (see analyze_song).

    Args:
        mp3_path: Path to the audio file
        stem: drums | bass | vocals | other
        kind: onsets | energy | silences
        start_ms: Window start (default: track start)
        end_ms: Window end, exclusive (default: track end)
        max_events: Maximum events or points to return
        resolution: beat | bar (energy only)
    """
    from xlights_mcp.audio.stem_events import stem_events, validate_stem_query

    error = validate_stem_query(stem, kind, resolution)
    if error:
        return {"error": error}
    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    analysis = await _analyze_in_thread(path, ctx)
    return stem_events(analysis, stem, kind, start_ms, end_ms, max_events, resolution)
```

- [ ] **Step 5: Preload madmom.** In `_preload_audio_stack`, before the `demucs`/`torch` try block, add:

```python
        try:
            import madmom.features.downbeats  # noqa: F401
        except ImportError:
            pass
```

- [ ] **Step 6: Run the tool tests, then the full suite**

Run: `.venv/Scripts/python -m pytest tests/test_analyze_song_tool.py -v`
Expected: all pass
Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass

- [ ] **Step 7: Lint what you touched**

Run: `.venv/Scripts/python -m ruff check src/xlights_mcp/server.py tests/test_analyze_song_tool.py`
Expected: no findings in lines added by this task (pre-existing findings elsewhere in `server.py` are out of scope)

- [ ] **Step 8: Commit**

```bash
git add src/xlights_mcp/server.py tests/test_analyze_song_tool.py
git commit -m "Expose stem summary in analyze_song and add get_stem_events tool" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Packaging — madmom from git

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md:81-82`

- [ ] **Step 1: Edit `pyproject.toml`.** Replace the `beats` extra and add two tables:

```toml
beats = [
    "madmom @ git+https://github.com/CPJKU/madmom.git@27f032e8947204902c675e5e341a3faf5dc86dae",
]
```

```toml
[tool.hatch.metadata]
allow-direct-references = true

[tool.uv.extra-build-dependencies]
madmom = ["cython", "setuptools", "numpy"]
```

(`allow-direct-references` is required: hatchling rejects `@ git+` dependencies without it.)

- [ ] **Step 2: Verify the extra installs from scratch** (throwaway venv, so the real one is untouched):

```bash
S="$TEMP/madmom-pkgtest"; rm -rf "$S"
uv venv -q "$S" --python 3.12
uv pip install --python "$S/Scripts/python.exe" -e ".[beats]" 2>&1 | tail -3
"$S/Scripts/python.exe" -c "import madmom.features.downbeats; print('madmom ok')"
```

Expected: `madmom ok`.
If uv errors that `extra-build-dependencies` is unknown or preview-only: delete the `[tool.uv.extra-build-dependencies]` table, and instead document the pre-install in README (Step 4 text gains: `uv pip install cython setuptools numpy` then `uv pip install --no-build-isolation -e ".[beats]"`). Re-run this step with those commands to confirm, then `rm -rf "$S"`.

- [ ] **Step 3: Install madmom into the project venv** (don't reinstall the project itself — a running MCP server locks its entry-point exe):

```bash
uv pip install cython setuptools
uv pip install --no-build-isolation "madmom @ git+https://github.com/CPJKU/madmom.git@27f032e8947204902c675e5e341a3faf5dc86dae"
.venv/Scripts/python -c "import madmom.features.downbeats; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: README** — replace the two "Better beat detection" lines with:

```bash
# Better beat detection (madmom, built from source — needs a C compiler;
# on Windows install "Desktop development with C++" from the VS Build Tools)
uv pip install -e ".[beats]"
```

- [ ] **Step 5: Full suite** (madmom now active in `detect_beats` for non-mocked tests)

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md
git commit -m "Install madmom from a pinned git commit for the beats extra" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Reference-track verification

Manual check against the real track the sharp-edges log was written from. Not a CI test.

- [ ] **Step 1: Run a forced analysis and print what matters**

```bash
.venv/Scripts/python - <<'PY'
import warnings; warnings.filterwarnings("ignore")
from pathlib import Path
from xlights_mcp.audio.analyzer import full_analysis
from xlights_mcp.config import load_config

mp3 = Path(r"E:\XLights\HalloweenShow\Music\GhostsnStuffft.RobSwire.mp3")
a = full_analysis(mp3, load_config().audio, force=True)
b = a.beats
print(f"tempo {b.tempo:.1f} source={b.beat_source} aligned={b.drum_aligned}")
for name, t in (("drop 1", 66.873), ("breakdown", 110.086), ("drop 2", 140.388)):
    d = min(b.downbeat_times, key=lambda x: abs(x - t))
    print(f"{name:9s} nearest downbeat {d:8.3f} ({1000*(d-t):+.0f} ms)")
for s in a.sections:
    print(f"{s.label:10s} {s.start_time:7.2f}-{s.end_time:7.2f} drums={s.drums} src={s.structure_source}")
PY
```

- [ ] **Step 2: Check against the spec's acceptance criteria**
  - drop 1 and drop 2 nearest downbeats within ±30 ms
  - a section starts within one beat (~465 ms) of 110.086 s, labelled `breakdown`, `drums=decaying`
  - labels read `intro … build → drop … breakdown (→ build) → drop … (outro)`, `src=stems`

If any criterion fails, stop and report the printed output — do not tune thresholds without discussing.

- [ ] **Step 3: Final full suite and lint**

Run: `.venv/Scripts/python -m pytest -q`
Run: `.venv/Scripts/python -m ruff check src/xlights_mcp/audio/stems_model.py src/xlights_mcp/audio/sections.py src/xlights_mcp/audio/drums.py src/xlights_mcp/audio/edm_structure.py src/xlights_mcp/audio/stem_events.py tests/drum_fixtures.py tests/test_drums.py tests/test_beat_grid.py tests/test_edm_structure.py tests/test_structure_modes.py tests/test_stem_events.py tests/test_pipeline_order.py tests/test_engine_labels.py`
Expected: all tests pass; no findings in these new files. For modified files (`analyzer.py`, `beats.py`, `structure.py`, `server.py`, `engine.py`, `cache.py`, the two modified test files) only findings in changed lines matter.

- [ ] **Step 4: Hand off** with @superpowers:finishing-a-development-branch.
