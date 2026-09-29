# Hit-bounded stem silences and kick events

Date: 2026-09-29
Status: Approved design
Covers rank 2 of `E:\XLights\mcp-sharp-edges.md`. That rank bundles these findings:
- "Drum silences start when the kick's tail dies"
- "Stem silences end early too"
- "Beat grid vs kicks inside drops"
- two of the stem-dropout rough edges: merging nearby spans, and the `other`/`Instruments` naming mismatch

A `snap: beat|bar` option is deferred.

## Problem

Stem silences come from energy alone: the stem counts as silent when its normalised RMS stays below 0.05 for at least 1 s (`drums.find_silences`). This goes wrong in three ways, all measured on Ghosts 'n' Stuff:
- **Drum silences start late.** The last kick before the build is at 51.246 s, but the silence starts at 53.081 s because the kick's reverb tail stays above the threshold.
- **Bass silences end early.** The bridge silence ends at 123.62 s, but the bass doesn't come back until its first hit at 125.27 s. A faint rumble (mean 0.058) crosses the threshold first.
- **Drums read as present when they aren't.** 2:05.4–2:09.8 has no drum hits, but energy of about 0.06 (synth bleed) keeps it out of the silences.

Kicks are also invisible to callers. `onset_bass` tells kicks from hats for bar-1 anchoring, but no tool returns kicks. In drops, 4 of the 100 downbeats are 64–87 ms late against the kick, so accents timed to the grid land late.

## Scope

Query level only. The stored `StemOnsets.silences` (energy-based) and everything built on them stay unchanged:
- drum runs,
- bar-1 re-anchoring,
- EDM section labels and `sections[].drums`,
- "decaying" flags.

There's no `ANALYSIS_VERSION` bump and no re-analysis.

## Hit-bounded silences

A new module, `src/xlights_mcp/audio/silences.py`, provides:

```
bounded_silences(analysis, stem, min_ms=1000, merge_gap_ms=0) -> list[tuple[float, float]]  # seconds
```

The spans are computed over the whole song from the cached `onset_times`, the stored energy silences, the energy curve, the beat grid and the duration. Onsets are sorted and deduplicated first.

**Drums** are purely percussive, so hits bound their silences:
- Only audible hits count. A hit at `t` counts when the drum energy reaches `SILENCE_THRESHOLD` (0.05) somewhere in `[t - 0.03, t + 0.1]` s.
  - Quieter onsets are bleed from other instruments, 27–39 dB below the mix. A hit too quiet to end an energy silence shouldn't end a hit silence either.
  - `kicks()` isn't affected; no ghost hit on the eight test songs reaches the kick threshold.
- The candidate spans are:
  - the gap before the first hit, `[0, first)`;
  - the gaps between consecutive hits `a` and `b`, as `[beat_after(a), b)`;
  - the gap after the last hit, `[beat_after(last), duration)`.
- A drum stem with no hits is one span covering the whole song.
- `beat_after(t)` is the first grid beat strictly later than `t + 0.1 s`, so a hit on or up to 100 ms before a beat moves to the next beat. When there's no such beat, or the grid has fewer than 2 beats, `beat_after(t)` is `t + beat_period`. `beat_period` is the median grid interval, or 0.5 s when the grid has fewer than 2 beats.
- Spans with `end <= start` are dropped.
- **Roll veto:** a candidate whose median drum energy is at least `3 × SILENCE_THRESHOLD` (0.15) is dropped. That covers drum rolls and orchestral swells, which are loud but have no detected hits.

**Bass, other, vocals** are sustained, so a held note has no new hit but is still sounding. For each stored energy silence `[s, e)`:
- The start stays `s`.
- The end is the first energy frame at or after `e` where energy is at least `2 × SILENCE_THRESHOLD` (0.1). The stem has to be clearly back, which a faint rumble isn't.
  - If a hit lies within 0.1 s of that frame, the end snaps to the nearest such hit.
  - If energy never reaches 0.1, the end is the duration.
  - There's no cap on how far the end can move. A quiet-but-present stretch (energy 0.05–0.1) counts as silent however long it lasts, and can join the next stored silence. On Ghosts, vocals run silent across 153.3–169.2 s, which matches the track.
- Hits inside `[s, e)` don't split or shorten the span.
- Ends can move a little earlier, by at most 0.1 s, when they snap to a hit.
- Their measured results on Ghosts:

  | Span | New end |
  |---|---|
  | bridge bass (was 123.62) | 125.272, the bass's return hit |
  | intro bass | 7.709 |
  | `other` spans | stay within 0.3 s of their stored ends |

**Then, for every stem:**
1. Clamp each span to `[0, duration]`.
2. Drop spans shorter than `min_ms`.
3. Merge spans whose gap is less than `merge_gap_ms`. Overlapping or touching spans always merge, even at 0.
4. Sort.

Filtering before merging matters: merging first would chain the tiny gaps between hi-hats into a span over real kicks.

For bass, other and vocals, a `min_ms` below 1000 rarely matters: their stored silences are at least 1 s long (`MIN_SILENCE_S`), though a span can come out up to 0.1 s shorter when its end snaps to a hit.

On Ghosts, the defaults give 4 drum spans: [0, 7.036), [51.710, 65.945), [110.540, 139.482), [184.041, 187.288).
- The breakdown is a single span because its stray FX onset at 137.509 is a ghost hit (peak energy 0.028).
- A drum silence can end on a kickless pickup a beat before the drop: 65.945 and 139.482 here. The drop's own hit is the next kick.

## Kicks

`kicks(analysis) -> list[float]` returns the drum hits whose `onset_bass` is at least `drums.KICK_THRESHOLD` (0.3), sorted and deduplicated.
- It raises `ValueError` when stems are unavailable, the drums stem is missing, or `onset_bass` doesn't line up with `onset_times`. Callers decide how to report that.
- Zero kicks is a valid empty list.
- On Ghosts, 252 of the 526 drum hits are kicks, and 63 of the 100 downbeats have a kick within 100 ms.

## API

**`get_stem_events`:**
- **`kind="kicks"`** (added to `VALID_KINDS`) works only with `stem="drums"`. Any other stem gives "kind 'kicks' needs stem 'drums'". It returns `events_ms` in the same shape as `onsets`, with the same windowing and `max_events` truncation. A `ValueError` from `kicks()` comes back as `{"error": ...}`.
- **`kind="silences"`** returns `bounded_silences(...)` spans:
  - computed over the whole song, then clipped to `start_ms`/`end_ms` as today, so a clipped span can be shorter than `min_ms`;
  - new parameters `min_ms` (default 1000) and `merge_gap_ms` (default 0).
- **Validation:** `validate_stem_query` checks both new parameters for every kind. The errors are "min_ms must be >= 0" and "merge_gap_ms must be >= 0".
- **The `instruments` alias:** `stem` is matched case-insensitively, and `"instruments"` means `other`. The alias is resolved before validation and listed in the "Unknown stem" message. The response reports `stem: "other"`.
- **Docstring:** one line each on the drum and sustained rules. It also says:
  - a drum silence can end on a pickup, so use `kind="kicks"` for the drop hit;
  - `merge_gap_ms` of about 150–500 joins silences split by a stray hit;
  - for sparse material, such as one hit per bar in a ballad build, raise `min_ms` to about one bar (see `get_beat_map` for the tempo).

**`analyze_song`:** the `stems.<name>.silences_ms` summary uses `bounded_silences` with default parameters, clamped to the duration, so it agrees with `get_stem_events`. The docstring notes that `sections[].drums` still comes from the energy-based structure analysis.

**`write_sequence` timing tracks:**
- `"Kicks"` joins `STEM_TRACK_NAMES` and `TIMING_TRACK_NAMES`, but not `_STEM_TRACKS`. That table's generic branch emits every onset of a stem.
- `build_timing_tracks` builds it from `kicks()`: one mark per kick, frame-rounded, each ending where the next starts.
- When `kicks()` raises or returns no kicks, the track is skipped with a warning, as `Drums` is without stems.
- The existing check against model and group names applies.

**`create_sequence`:**
- `Kicks` joins `STEM_TRACK_NAMES`, which the baseline already requests whenever stems are available.
- Each downbeat accent starts at the nearest kick within 100 ms of the downbeat, or at the downbeat itself when there's none, and is then frame-rounded.
- When `kicks()` raises, accents stay on downbeats with no warning. The Kicks track's own warning already says so.
- The existing "not in the last frame" guard still applies.

**Playbook (`sequence_song.md`):** step 1 says to time dropouts from `get_stem_events(kind="silences")` (with `merge_gap_ms` to join split dropouts) and hits from `kind="kicks"`, and lists the `Kicks` timing track.

## Testing

**Unit tests with synthetic `StemOnsets`, energy curves and beat grids:**
- **Drums:**
  - a silence starts on the beat after the last hit, not at the energy start (the tail case);
  - a stretch with no hits but some energy is silent (the bleed case);
  - an empty stem is silent throughout;
  - a hit on a beat, or up to 100 ms before it, moves to the next beat;
  - a span past the end of the grid uses `beat_period`, and a grid with fewer than 2 beats uses 0.5 s;
  - duplicate onsets are handled;
  - a quiet ghost onset (energy under 0.05 around it) doesn't split a silence or mark a silent stretch present;
  - a candidate with median energy of at least 0.15 and no hits (a roll) is dropped.
- **Sustained stems:**
  - the end moves to the hit where energy returns above 0.1 (the rumble case);
  - a held note right after a silence, with no hit and energy above 0.1, keeps the stored end (the intro-bass case);
  - energy that never returns runs the span to the duration;
  - two stored silences joined by a quiet 0.05–0.1 stretch become one span;
  - hits inside a span don't split it;
  - the start is unchanged.
- **`min_ms` and `merge_gap_ms`:**
  - filtering happens before merging (a busy hi-hat stretch doesn't become silent);
  - overlapping and touching spans merge at 0;
  - spans clamp to the duration;
  - negative values are rejected.
- **Kicks:** the threshold boundary, sorting, deduplication, and each error case.
- **Tools:**
  - `get_stem_events` returns kicks, and bounded silences with the new parameters;
  - the `instruments` alias works in any case;
  - kicks with a non-drums stem is an error;
  - the `analyze_song` summary uses the bounded spans.
- **Timing tracks:** a `Kicks` track is built, and with no stems or no kicks it's a warning.
- **Baseline:**
  - an accent snaps to a kick 60 ms early;
  - an accent stays on the downbeat when the nearest kick is 150 ms away;
  - the `Kicks` track is present with stems.

**Manual check against the cached Ghosts 'n' Stuff analysis:**
- the drum silence starts at 51.710;
- the bridge bass silence ends at 125.272;
- the intro bass silence still ends at about 7.7;
- drums are silent across 125.4–129.8 s;
- the breakdown is one span, [110.540, 139.482), at the default `merge_gap_ms=0`;
- every accent within 100 ms of a kick sits on the kick's frame, and the 4 that were 64–87 ms late
  move by two or more frames (for example 79.290 → 79.226 and 149.140 → 149.072).

## Cross-song validation

The rules were checked on eight songs chosen for different styles, analysed with stems:

| Song | Style | BPM |
|---|---|---|
| Ghosts 'n' Stuff | EDM | 130 |
| Deck the Halls Remix | EDM | 130 |
| Carnival (Xmas Edition) | soca | 130 |
| Remains of the Day | swing | 162 |
| Let It Go (Idina Menzel) | ballad | 136 |
| Superstition | live funk | 102 |
| Dance of the Sugar Plum Fairy (Pentatonix) | a cappella and beatbox | 154 |
| Beetlejuice Main Title | orchestral | 146 |

The first draft only covered Ghosts. It overfit the drum rule in two places:
- **Ghost hits** split real silences or marked silent stretches present. Let It Go's silent first 88 s came back as 7 fragments with about 35 s marked "present", and Sugar Plum's opening split into 9 spans. Corpse Bride, Deck's intro and Superstition's fade-out were also affected.
- **Rolls and swells** were called silent: Carnival's build roll at median energy 0.58, and six Beetlejuice spans.

The audible-hit filter and the roll veto fix both, and the Ghosts checks above still hold. The closest calls on the veto: the highest median it keeps is 0.10 and the lowest it drops is 0.18.

Checked and deliberately not changed:
- **A tempo-relative minimum length**, such as one bar. It deletes real 3-beat stops, for example three in Deck, including the stop before a drop. Sparse patterns with one audible hit per bar, like Let It Go's build and Beetlejuice's outro, still produce short spans. The stored energy method produces the same ones, so the docstring points to `min_ms` instead.
- **A stem-relative exit threshold for sustained stems.** Stems with a low median are absent most of the time; their level while playing is 0.14–0.74, always above 0.1. Every added stretch has mean energy of 0.08 or less, and extensions over 2 bars have 0.03 or less.
- **The kick threshold.** Accent-snap shifts above 25 ms are 0–4 per song, all early kicks, at most 92 ms. Songs with few kicks (Let It Go, Sugar Plum) correctly keep accents on the grid. 0.3 matches bar-1 anchoring. Soft-kick songs vary in kick count between 0.2 and 0.4, but accents don't.
