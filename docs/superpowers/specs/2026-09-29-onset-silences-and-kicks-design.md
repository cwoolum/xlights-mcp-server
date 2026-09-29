# Hit-bounded stem silences and kick events

Date: 2026-09-29
Status: Approved design
Covers rank 2 of `E:\XLights\mcp-sharp-edges.md`. That rank bundles these findings:
- "Drum silences start when the kick's tail dies"
- "Stem silences end early too"
- "Beat grid vs kicks inside drops"
- the stem-dropout rough edges (merging, the `other`/`Instruments` naming mismatch, spans past the grid)

## Problem

Stem silences come from energy alone: the stem counts as silent when its normalised RMS stays below 0.05 for at least 1 s (`drums.find_silences`). This goes wrong in three ways, all measured on Ghosts 'n' Stuff:
- **Drum silences start late.** The last kick before the build is at 51.246 s, but the silence starts at 53.081 s because the kick's reverb tail stays above the threshold.
- **Bass silences end early.** The bridge silence ends at 123.62 s, but the bass doesn't come back until its first hit at 125.27 s. A faint rumble crosses the threshold first.
- **Drums read as present when they aren't.** 2:05.4–2:09.8 has no drum hits, but energy of about 0.06 (synth bleed) keeps it out of the silences.

Kicks are also invisible to callers. `onset_bass` tells kicks from hats for bar-1 anchoring, but no tool returns kicks. In some drop bars the beat grid runs up to about 80 ms off the kick, so accents timed to the grid land slightly late.

## Scope

Query level only. The stored `StemOnsets.silences` (energy-based) and everything built on them stay unchanged:
- drum runs,
- bar-1 re-anchoring,
- EDM section labels,
- "decaying" flags.

There's no `ANALYSIS_VERSION` bump and no re-analysis. Feeding hit-bounded silences into structure is a possible later change.

## Hit-bounded silences

A new module, `src/xlights_mcp/audio/silences.py`, provides:

```
bounded_silences(analysis, stem, min_ms=1000, merge_gap_ms=0) -> list[tuple[float, float]]  # seconds
```

The result is computed from the cached analysis: `onset_times`, `silences`, the beat grid and the duration.

**Drums**, being purely percussive, are bounded by their hits:
- The candidate spans are:
  - the gap before the first hit, `[0, first)`;
  - the gaps between consecutive hits `a` and `b`, as `[beat_after(a), b)`;
  - the gap after the last hit, `[beat_after(last), duration)`.
- A drum stem with no hits is one span covering the whole song.
- `beat_after(t)` is the first grid beat later than `t + 0.05 s`, so a hit that sits on a beat moves to the next beat. When `t` is past the last grid beat, `beat_after(t)` is `t + beat_period`, where `beat_period` is the median beat interval (0.5 s without a grid). The result is capped at the duration.
- Spans with `end <= start` are dropped.

**Bass, other, vocals** are sustained, so their hits don't mark the silence start. A held note has no new hit but is still sounding. For each stored energy silence `[s, e)`:
- The start stays `s`.
- The end becomes the first hit at or after `e - 0.1 s`, if that hit is no more than 2 bars (8 beat periods) after `e`. Otherwise the end stays `e`.
- A hit inside `[s, e)` below the energy threshold is ignored.

**Then, for every stem:**
1. Merge spans whose gap is less than `merge_gap_ms`.
2. Drop spans shorter than `min_ms`.
3. Return the spans sorted.

## Kicks

`kicks(analysis) -> list[float]` returns the drum hits whose `onset_bass` is at least `drums.KICK_THRESHOLD` (0.3), sorted. If `onset_bass` doesn't line up with `onset_times` (a malformed cache), the result is an error rather than an empty list.

## API

**`get_stem_events`:**
- `kind` gains `"kicks"`, which works only with `stem="drums"` (anything else is an error). It returns `events_ms` in the same shape as `onsets`, with the same windowing and `max_events` truncation.
- `kind="silences"` returns `bounded_silences(...)` spans. It gains `min_ms` (default 1000, at least 0) and `merge_gap_ms` (default 0, at least 0); both are ignored for other kinds.
- `stem="instruments"` is an alias for `other`, matching the `Instruments` timing track. The response reports `stem: "other"`.
- The docstring describes the drum and sustained-stem rules in one line each.

**`analyze_song`:** the `stems.<name>.silences_ms` summary uses `bounded_silences` with default parameters, so it agrees with `get_stem_events`.

**`write_sequence`:** `timing_tracks` accepts `"Kicks"`, one mark per kick. Marks are frame-rounded and each one ends where the next starts, like the other onset tracks. Without stems the track is skipped with a warning, like `Drums`.

**`create_sequence`:**
- The baseline adds the `Kicks` timing track whenever stems are available.
- Each downbeat accent starts at the nearest kick within 100 ms of the downbeat, or at the downbeat itself when there's none, and is then frame-rounded. The existing "not in the last frame" guard still applies.

**Playbook (`sequence_song.md`):** step 1 says to time dropouts from `get_stem_events(kind="silences")` and hits from `kind="kicks"`. It also lists the `Kicks` timing track.

## Testing

**Unit tests with synthetic `StemOnsets` and beat grids:**
- **Drums:**
  - a silence starts on the beat after the last hit, not at the energy start (the tail case);
  - a stretch with no hits but some energy is silent (the bleed case);
  - an empty stem is silent throughout;
  - a hit on a beat moves to the next beat;
  - a span past the end of the grid uses `beat_period`.
- **Sustained stems:**
  - the end moves to the next hit within 2 bars (the rumble case);
  - the end stays when the next hit is too far away;
  - a held note with no hits and energy above the threshold isn't silent;
  - the start is unchanged.
- **`min_ms` and `merge_gap_ms`**, including zero and negative values (negative is rejected).
- **Kicks:** the threshold boundary, sorting, a non-drums stem is an error, and a length mismatch is an error.
- **Tools:**
  - `get_stem_events` returns kicks and bounded silences with the new parameters;
  - the `instruments` alias works;
  - the `analyze_song` summary uses the bounded spans.
- **Timing tracks:** a `Kicks` track is built, and without stems it's a warning.
- **Baseline:**
  - an accent snaps to a kick 60 ms away;
  - an accent stays on the downbeat when the nearest kick is 150 ms away;
  - the `Kicks` track is present with stems.

**Manual check against the cached Ghosts 'n' Stuff analysis:**
- the drum silence after 51.246 s starts at the next beat, about 51.7 s, not 53.08;
- the bridge bass silence ends at 125.27 s, not 123.62;
- drums are silent across 2:05.4–2:09.8;
- the section labels and drop anchors are unchanged.
