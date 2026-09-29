"""MCP Server entry point for xLights Sequence Generator."""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import anyio
from mcp.server.fastmcp import Context, FastMCP

from xlights_mcp.config import ServerConfig, load_config, save_config

logger = logging.getLogger(__name__)

# Initialize MCP server
mcp = FastMCP(
    "xLights Sequence Generator",
    instructions="Analyze music and generate xLights light show sequences. "
    "Use list_shows/switch_show to manage show folders, analyze_song to analyze music, "
    "and create_sequence to generate .xsq files.",
)

# Global config — loaded at startup
_config: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Get the current server configuration."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _active_show(config: ServerConfig) -> Path | dict:
    """The active show folder, or an action_required dict when none is usable."""
    show_path = config.active_show_path
    if not show_path or not show_path.exists():
        return {
            "error": "No active show folder configured.",
            "action_required": "Ask the user for the path to their xLights show directory and call add_show_folder.",
        }
    return show_path


def _show_file(show_path: Path, value: str, suffix: str = "") -> Path:
    """`value` as a path: relative ones resolve against the show folder; `suffix` is added when missing."""
    path = Path(value).expanduser()
    if suffix and path.suffix.lower() != suffix:
        path = path.with_name(path.name + suffix)
    return path if path.is_absolute() else show_path / path


def _resolve_show(config: ServerConfig, show_name: str | None) -> dict | Path:
    """Resolve which show folder to use.

    Returns a Path on success, or a dict with action_required on ambiguity.
    """
    if show_name:
        show_path = config.get_show_path(show_name)
        if not show_path or not show_path.exists():
            return {
                "error": f"Show '{show_name}' not found.",
                "available_shows": config.list_shows(),
                "action_required": "Ask the user which show folder to use.",
            }
        return show_path

    shows = config.list_shows()
    if not shows:
        return {
            "error": "No show folders configured.",
            "action_required": "Ask the user for their xLights show directory and call add_show_folder.",
        }

    if len(shows) == 1:
        return config.get_show_path(shows[0])

    # Multiple shows — ask the user to choose
    return {
        "status": "show_selection_required",
        "available_shows": shows,
        "active_show": config.active_show,
        "action_required": (
            "Multiple show folders are configured. Ask the user which show "
            "this sequence should go into. Then call this tool again with "
            "the show_name parameter set."
        ),
    }


# ---------------------------------------------------------------------------
# Show Management Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_shows() -> dict:
    """List all configured xLights show folders.

    Returns the available show folders (e.g., Christmas, Halloween) and
    indicates which one is currently active.
    """
    config = get_config()
    if not config.show_folders:
        if config.detected_folders:
            detected = {}
            for name, path_str in config.detected_folders.items():
                path = Path(path_str).expanduser()
                detected[name] = str(path)
            return {
                "status": "setup_required",
                "detected_folders": detected,
                "action_required": (
                    "xLights show folders were detected at the paths listed above. "
                    "Ask the user if they'd like to use these, or provide their own show directory path. "
                    "Call add_show_folder with the path they choose."
                ),
            }
        return {
            "error": "No xLights show folders found.",
            "action_required": (
                "Ask the user for the full path to their xLights show directory. "
                "This is the folder that contains their xlights_rgbeffects.xml file. "
                "Once they provide it, call add_show_folder with the path."
            ),
        }
    shows = {}
    for name, path_str in config.show_folders.items():
        path = Path(path_str).expanduser()
        shows[name] = {
            "path": str(path),
            "exists": path.exists(),
            "active": name == config.active_show,
        }
    return {"shows": shows, "active": config.active_show}


@mcp.tool()
def add_show_folder(path: str, name: str | None = None) -> dict:
    """Add an xLights show folder by path.

    Use this to confirm a detected show folder or provide a custom path.
    The folder must contain an xlights_rgbeffects.xml file.

    Args:
        path: Full filesystem path to the xLights show folder
        name: Optional display name for the show (derived from folder name if omitted)
    """
    config = get_config()
    show_path = Path(path).expanduser().resolve()

    if not show_path.exists():
        return {"error": f"Path does not exist: {show_path}"}

    if not show_path.is_dir():
        return {"error": f"Path is not a directory: {show_path}"}

    if not (show_path / "xlights_rgbeffects.xml").exists():
        return {
            "error": f"Not a valid xLights show folder (missing xlights_rgbeffects.xml): {show_path}",
            "hint": "The show folder should contain xlights_rgbeffects.xml, which xLights creates automatically.",
        }

    show_name = name or show_path.name.lower()
    config.show_folders[show_name] = str(show_path)
    if not config.active_show:
        config.active_show = show_name
    config.detected_folders = {}
    save_config(config)

    global _config
    _config = config

    return {
        "success": True,
        "show_name": show_name,
        "path": str(show_path),
        "active": config.active_show == show_name,
    }


@mcp.tool()
def switch_show(show_name: str) -> dict:
    """Switch the active xLights show folder.

    Args:
        show_name: Name of the show to activate (e.g., "christmas", "halloween")
    """
    config = get_config()
    if show_name not in config.show_folders:
        return {
            "error": f"Unknown show '{show_name}'. Available: {config.list_shows()}"
        }

    config.active_show = show_name
    save_config(config)
    return {"active_show": show_name, "path": str(config.active_show_path)}


@mcp.tool()
def list_models(include_placeholders: bool = False) -> dict:
    """List all light models in the active xLights show.

    Returns model names, types, controller assignments, and channel info.
    Layout-only placeholder models ("Dont Map", "Do Not Map") are hidden unless
    include_placeholders is true. Use get_show_layout for groups and tiers.
    """
    from xlights_mcp.xlights.show import load_show_models

    config = get_config()
    show_path = _active_show(config)
    if isinstance(show_path, dict):
        return show_path

    models = [m for m in load_show_models(show_path) if include_placeholders or not m.is_placeholder]
    return {
        "show": config.active_show,
        "model_count": len(models),
        "models": [m.model_dump() for m in models],
    }


@mcp.tool()
def get_show_layout(show_name: str | None = None) -> dict:
    """Get the show's model groups with a suggested sequencing tier for each.

    Tiers: "wash" = broad parent groups for a base layer (e.g. All, House);
    "feature" = top-level props that carry motion (e.g. Roof Edges, Pipes);
    "skip" = empty, preview-only, submodel-row, single-prop or identical-to-another-group
    groups, or sub-parts of a feature. Every group is still usable by name. Each group
    lists its child and parent groups, prop count, height range (y_range) and, for small
    feature groups, accent_props (single props for accents). Tiers can be overridden in
    xlights-mcp.json in the show folder: {"tiers": {"Group Name": "feature"}}. Overriding
    a group can change which other groups count as its sub-parts, so check the result.

    Args:
        show_name: Show to describe (defaults to the active show)
    """
    from xlights_mcp.xlights.layout import build_show_layout
    from xlights_mcp.xlights.show import load_show_config

    config = get_config()
    show_path = _resolve_show(config, show_name) if show_name else _active_show(config)
    if isinstance(show_path, dict):
        return show_path

    layout = build_show_layout(load_show_config(show_path))
    layout["show"] = show_name or config.active_show
    return layout


@mcp.tool()
def list_controllers() -> dict:
    """List all controllers configured in the active xLights show.

    Returns controller names, IPs, protocols, and channel counts.
    """
    from xlights_mcp.xlights.show import load_show_controllers

    config = get_config()
    show_path = _active_show(config)
    if isinstance(show_path, dict):
        return show_path

    controllers = load_show_controllers(show_path)
    return {
        "show": config.active_show,
        "controller_count": len(controllers),
        "controllers": [c.model_dump() for c in controllers],
    }


@mcp.tool()
def list_sequences() -> dict:
    """List all sequences (.xsq files) in the active show folder.

    `generated` is true for sequences written by create_sequence/write_sequence, false for
    hand-made ones, and null when the file can't be read. `modified` is the file's last-modified time.
    """
    from xlights_mcp.xlights.xsq_reader import is_generated_file

    config = get_config()
    show_path = _active_show(config)
    if isinstance(show_path, dict):
        return show_path

    sequences = []
    for xsq in sorted(p for p in show_path.glob("*.xsq") if p.is_file()):
        try:
            generated = is_generated_file(xsq)
        except OSError:
            generated = None
        try:
            modified = datetime.fromtimestamp(xsq.stat().st_mtime, tz=UTC).astimezone().isoformat(timespec="seconds")
        except OSError:
            modified = None
        sequences.append({"name": xsq.stem, "path": str(xsq), "generated": generated, "modified": modified})
    return {
        "show": config.active_show,
        "sequence_count": len(sequences),
        "sequences": sequences,
    }


@mcp.tool()
def inspect_sequence(sequence_name: str) -> dict:
    """Inspect an existing xLights sequence file.

    Shows the song info, duration, models used, and effect summary.

    Args:
        sequence_name: Name of the sequence (without .xsq extension)
    """
    from xlights_mcp.xlights.xsq_reader import read_xsq_summary

    if not sequence_name.strip():
        return {"error": "sequence name is required"}
    config = get_config()
    show_path = _active_show(config)
    if isinstance(show_path, dict):
        return show_path

    xsq_path = _show_file(show_path, sequence_name, ".xsq")
    if not xsq_path.exists():
        return {"error": f"Sequence not found: {xsq_path}"}

    return read_xsq_summary(xsq_path)


@mcp.tool()
def profile_sequence(xsq_path: str) -> dict:
    """Style profile of a sequence, measured against the active show's layout.

    Use a hand-made sequence as the target style for a new one:
    - lit_at_once: elements lit at the same moment (median / p90 / max), sampled every 50 ms
    - dark_share: share of the song with nothing lit ("Off" effects count as dark)
    - parent_lit_with_contained: per group, the share of its lit time when a group or model
      inside it is also lit (how often parents act as a base under their children)
    - overlaps_within_layer: overlapping effects on one element layer (hand-made sequences have 0)
    - elements: per element (the 20 busiest), its layers, effect count, median effect length,
      share of the song lit and top effect names; other_elements summarises the rest.
      effects includes effects on strands, nodes and submodels, and sub_effects counts those
      (layers lists only the element's own effect layers)

    Args:
        xsq_path: The sequence file; a name or relative path resolves against the active show
            folder, and ".xsq" is added when missing
    """
    from xlights_mcp.xlights.profile import profile_sequence as build_profile
    from xlights_mcp.xlights.show import load_show_config

    if not xsq_path.strip():
        return {"error": "sequence name is required"}
    config = get_config()
    show_path = _active_show(config)
    if isinstance(show_path, dict):
        return show_path
    path = _show_file(show_path, xsq_path, ".xsq")
    if not path.is_file():
        return {"error": f"Sequence not found: {path}"}
    try:
        return build_profile(path, load_show_config(show_path))
    except (ET.ParseError, ValueError, OSError) as e:
        return {"error": f"Could not read {path.name}: {e}"}


@mcp.tool()
def list_effects() -> dict:
    """List all available xLights effects with descriptions.

    Returns effect names, descriptions, and which model types they work best on.
    """
    from xlights_mcp.xlights.effects import get_effect_library

    return {"effects": get_effect_library()}


# ---------------------------------------------------------------------------
# Audio Analysis Tools
# ---------------------------------------------------------------------------


def _progress_forwarder(ctx: Context):
    """Build a progress callback usable from a worker thread that notifies the client."""

    def on_progress(done: int, total: int, message: str) -> None:
        # Runs on the worker thread; hop back to the event loop to notify the client.
        anyio.from_thread.run(ctx.report_progress, done, total, message)

    return on_progress


_analysis_locks: dict[str, threading.Lock] = {}
_analysis_locks_guard = threading.Lock()


def _analysis_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _analysis_locks_guard:
        return _analysis_locks.setdefault(key, threading.Lock())


async def _analyze_in_thread(path: Path, ctx: Context, force: bool = False):
    """Run full_analysis off the event loop, forwarding stage progress to the client.

    Calls for the same file run one at a time: parallel tool calls would otherwise
    run duplicate pipelines that write the same stems directory concurrently. A
    waiting call then finds the first call's result in the cache.
    """
    from xlights_mcp.audio.analyzer import full_analysis

    config = get_config()
    on_progress = _progress_forwarder(ctx)
    lock = _analysis_lock(path)

    def run():
        with lock:
            return full_analysis(path, config.audio, progress=on_progress, force=force)

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def analyze_song(mp3_path: str, ctx: Context, force: bool = False) -> dict:
    """Analyze a music file for light show sequencing.

    Performs full audio analysis: beat detection, song structure,
    frequency spectrum, energy profile, and source separation. Separation is
    always attempted; it's a no-op when Demucs isn't installed. Progress is
    streamed as MCP progress notifications while it runs.

    Results are cached on disk keyed by file content, so repeat calls (and
    create_sequence on the same file) return instantly. Returns a compact
    summary; use get_beat_map / get_energy_profile / get_song_structure / get_stem_events for
    detailed data.

    The response also includes: stems is a per-stem summary
    {onsets, mean_energy, silences_ms} keyed by "drums"/"bass"/"vocals"/"other", or
    null when source separation is unavailable — in that case get_stem_events will
    also return an error. silences_ms uses the same hit-bounded spans as
    get_stem_events(kind="silences") with default parameters. sections[].drums is
    "present"/"absent"/"decaying" from the energy-based structure analysis, or null
    when that section's structure came from the mixdown only (no drum stem).
    beat_source ("madmom"/"librosa") and drum_aligned say whether the beat grid used
    the drum-aware pipeline; structure_source ("stems"/"mixdown") says the same for
    the song sections.

    Args:
        mp3_path: Path to the audio file to analyze (.mp3, .wav, .ogg, ...)
        force: Re-run analysis even if a cached result exists
    """
    from xlights_mcp.audio.stem_events import stems_summary

    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    started = time.monotonic()
    analysis = await _analyze_in_thread(path, ctx, force=force)
    elapsed = time.monotonic() - started

    return {
        "file_name": analysis.file_name,
        "duration_seconds": round(analysis.duration_seconds, 2),
        "tempo_bpm": round(analysis.beats.tempo, 1),
        "beat_count": len(analysis.beats.beat_times),
        "onset_count": len(analysis.beats.onset_times),
        "beat_source": analysis.beats.beat_source,
        "drum_aligned": analysis.beats.drum_aligned,
        "structure_source": analysis.sections[0].structure_source if analysis.sections else "mixdown",
        "sections": [s.model_dump() for s in analysis.sections],
        "peak_loudness_time": round(analysis.spectrum.peak_loudness_time, 2),
        "dynamic_range": round(analysis.spectrum.dynamic_range, 2),
        "stems": stems_summary(analysis),
        "cached": analysis.cached,
        "elapsed_seconds": round(elapsed, 1),
    }


@mcp.tool()
async def get_song_structure(mp3_path: str, ctx: Context) -> dict:
    """Get the song's section structure.

    EDM tracks (with a mid-song structural drum gap) are labelled intro/build/
    drop/breakdown/outro; other tracks get pop-song labels (verse/chorus/
    bridge/intro/outro/transition/instrumental). Each section's
    structure_source ("stems"/"mixdown") says whether drum-stem presence drove
    the labelling, and drums ("present"/"absent"/"decaying", or null when
    structure_source is "mixdown") says whether the drums were present,
    absent, or fading out through that section.

    Served from the analysis cache when available (see analyze_song).

    Args:
        mp3_path: Path to the audio file
    """
    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    analysis = await _analyze_in_thread(path, ctx)
    return {"sections": [s.model_dump() for s in analysis.sections]}


@mcp.tool()
async def get_beat_map(mp3_path: str, ctx: Context) -> dict:
    """Get beat and downbeat timestamps for a song.

    beat_source ("madmom"/"librosa") says which beat tracker produced the
    grid. drum_aligned says whether it was snapped to drum-stem onsets and
    re-anchored to bar 1 at structural drum gaps; false means the grid is
    the plain mixdown-only detection.

    Served from the analysis cache when available (see analyze_song).

    Args:
        mp3_path: Path to the audio file
    """
    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    analysis = await _analyze_in_thread(path, ctx)
    return analysis.beats.model_dump()


@mcp.tool()
async def get_energy_profile(mp3_path: str, ctx: Context) -> dict:
    """Get energy and frequency band analysis for a song.

    Returns loudness curve and bass/mid/high energy over time.
    Served from the analysis cache when available (see analyze_song).

    Args:
        mp3_path: Path to the audio file
    """
    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    analysis = await _analyze_in_thread(path, ctx)
    return analysis.spectrum.model_dump()


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
    min_ms: int = 1000,
    merge_gap_ms: int = 0,
) -> dict:
    """Get per-stem events from source separation (drums, bass, vocals, other).

    Requires source separation to have run for this file: if analyze_song returned
    "stems": null, this returns {"error": ...}.

    kind="onsets": hit times in the window, e.g. drum hits or vocal phrase starts.
    Returns {"count", "events_ms": [int, ...]}; count is the total number of onsets
    in the window before any truncation.

    kind="energy": stem loudness over the window, one point per beat (resolution=
    "beat") or bar ("bar") span that starts inside the window. If the grid starts at
    least half a beat/bar after 0, an extra point at t_ms=0 covers the intro
    [0, first grid time); like any point, it is only returned when the window
    includes 0. Returns {"resolution", "points": [{"t_ms", "energy"}, ...]}; energy
    is 0-1, rounded to 3 decimal places.

    kind="kicks": kick-drum hit times in the window (drum hits with a kick's low
    end; drums only). Returns {"count", "events_ms": [int, ...]} like onsets.

    kind="silences": [start, end] ms spans where the stem is silent, clipped to the
    window. Returns {"spans_ms": [[start, end], ...]} and is never truncated. Drum
    silences run from the beat after the last audible hit to the next audible hit, so
    they start when the hits stop rather than when the last tail dies away; they mark
    a breakdown, riser, or other gap. Bass, instruments and vocals silences start
    where the stem goes quiet and end where it clearly returns. A drum silence can
    end on a pickup a beat before the drop, so use kind="kicks" for the drop hit.
    merge_gap_ms of about 150-500 joins dropouts split by a stray hit; raise min_ms
    to about a bar for sparse material such as one hit per bar in a ballad build
    (see get_beat_map for the tempo). Spans are found over the whole song and then
    clipped to the window.

    onsets, kicks and energy return at most max_events items; when the response has
    truncated=true, call again with start_ms=next_start_ms to continue. An invalid
    stem, kind, resolution, max_events, min_ms, merge_gap_ms, or window (start_ms >
    end_ms) returns {"error": ...} without analysing.

    Served from the analysis cache when available (see analyze_song).

    Args:
        mp3_path: Path to the audio file
        stem: drums | bass | vocals | other (alias: instruments)
        kind: onsets | energy | silences | kicks
        start_ms: Window start (default: track start)
        end_ms: Window end, exclusive (default: track end)
        max_events: Maximum events or points to return
        resolution: beat | bar (energy only)
        min_ms: Shortest silence to report (silences only)
        merge_gap_ms: Join silences closer together than this (silences only)
    """
    from xlights_mcp.audio.stem_events import stem_events, validate_stem_query

    error = validate_stem_query(
        stem,
        kind,
        resolution,
        max_events=max_events,
        start_ms=start_ms,
        end_ms=end_ms,
        min_ms=min_ms,
        merge_gap_ms=merge_gap_ms,
    )
    if error:
        return {"error": error}
    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    analysis = await _analyze_in_thread(path, ctx)
    return stem_events(
        analysis, stem, kind, start_ms, end_ms, max_events, resolution, min_ms, merge_gap_ms
    )


# ---------------------------------------------------------------------------
# Sequence Generation Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def create_sequence(
    mp3_path: str,
    ctx: Context,
    mode: str = "auto",
    palette_hint: str | None = None,
    theme: str | None = None,
    vocal_assignments: dict[str, str] | None = None,
    show_name: str | None = None,
) -> dict:
    """Create a baseline xLights sequence from a music file.

    "auto" writes a simple baseline: quiet sections (intro, outro, breakdown) get the
    largest wash group dimmed; other sections light half of the feature groups at a
    time, alternating by height; chorus, drop and instrumental sections add short hits
    on accent props at each downbeat. Without feature groups, the show's props take
    turns instead. It includes Beats and Bars timing tracks, plus
    Drums, Bass and Instruments when stems are available. It never overwrites an
    existing sequence; it picks "<song> (generated N)" instead. For a hand-made-style
    sequence, use the sequence_song prompt and write_sequence.

    Args:
        mp3_path: Path to the .mp3 file
        mode: Generation mode — "auto" (the baseline described above), "guided" (returns
              the analysis for an interactive session), "template" (not implemented yet)
        palette_hint: Optional colours: names (red, green, blue, white, warm white,
            yellow, orange, gold, purple, pink, magenta, cyan, ice) or #RRGGBB,
            separated by commas and/or "and". Unrecognised words are reported and
            ignored; with no usable hint, the theme's palette is used.
        theme: Optional theme: "christmas" or "halloween"; anything else uses the
            Christmas palettes
        vocal_assignments: Optional mapping of model names to vocal track names.
            Use {"all": "<track_name>"} to assign one track to all singing models,
            or map individual models like {"Snowman": "Vocals", "Bulb Blue": "Full Mix Vocals"}.
            If omitted and singing models are detected, returns available models and
            tracks so you can prompt the user for assignments.
        show_name: Which show folder to generate the sequence in (e.g., "christmas",
            "halloween"). If omitted and multiple shows exist, returns available
            shows so you can ask the user which one to use.
    """
    from xlights_mcp.sequencer.engine import generate_sequence
    from xlights_mcp.xlights.version import installed_xlights_version

    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    if mode not in ("auto", "guided", "template"):
        return {"error": f"Invalid mode '{mode}'. Use: auto, guided, template"}

    config = get_config()
    show_path = _resolve_show(config, show_name)
    if isinstance(show_path, dict):
        return show_path

    on_progress = _progress_forwarder(ctx)
    return await anyio.to_thread.run_sync(
        lambda: generate_sequence(
            mp3_path=path,
            show_path=show_path,
            mode=mode,
            palette_hint=palette_hint,
            theme=theme,
            audio_config=config.audio,
            vocal_assignments=vocal_assignments,
            progress=on_progress,
            xlights_version=installed_xlights_version(show_path),
        )
    )


@mcp.tool()
async def write_sequence(
    mp3_path: str,
    ctx: Context,
    plan: list[dict] | None = None,
    plan_path: str | None = None,
    name: str | None = None,
    timing_tracks: list[str] | None = None,
    overwrite: bool = False,
    validate_only: bool = False,
) -> dict:
    """Validate an effect plan against the active show and the song, then write it as an .xsq.

    Each placement: {"element", "layer", "effect", "start_ms", "end_ms", "settings", "palette",
    "blend"}.
    - element: a model or group name (list_models / get_show_layout); submodels aren't supported.
    - layer: 0-2 (default 0; 0 is drawn on top). effect: an xLights effect name (list_effects, or
      any effect already used in this show's sequences).
    - blend: how the placement mixes with the layers below it (default "Normal"). Useful ones:
      "Additive" (white or same-hue accents), "1 reveals 2" (coloured hits keep their colour),
      "Max" (texture over texture), "Layered" (fills the dark areas below). Any xLights mix
      type is accepted in any case; unknown names get suggestions. It is shorthand for
      T_CHOICE_LayerMethod, so don't give both.
    - settings: {key: value} (values must be strings, numbers or booleans, and can't contain
      commas) or a raw "K=V,K=V" string.
    - palette: {"colors": ["#RRGGBB", ...] (1-8), "brightness": 0-400 (default 100),
      "sparkles": 0-200 (default 0), "music_sparkles": true|false (default false, needs
      sparkles above 0)}; omitted means a white palette.

    Times are rounded to the 25 ms frame grid and clipped to the song end (counted under
    "adjusted"). Any error writes nothing: overlapping placements on the same element and layer,
    a bad layer, bad times (non-numeric, negative, empty after rounding, or starting at or after
    the song end), an unknown element or effect, an unknown placement or palette key (e.g. a
    misspelt "pallete"), malformed settings or palette, an unknown or duplicate timing track (a
    timing track can't share a name with a model or group), an invalid name, or an existing file
    without overwrite. A group lit while a group or model inside it is also lit
    is a warning, and so is a Color Wash, Plasma or On with Normal blending that lies over an
    effect on a higher layer of the same element for that effect's whole duration (it is
    completely hidden: put bases on the highest layer or give the upper effect a blend). So is
    a palette with music_sparkles true and sparkles 0 (music sparkles need sparkles above 0).
    The report lists at most 50 errors. Only the elements the plan uses are written, and the
    file carries the installed xLights version.

    Args:
        mp3_path: The song; analysed first when it isn't cached (like get_beat_map)
        plan: The placements. Pass this or plan_path, not both.
        plan_path: A JSON file holding the placement list; relative paths resolve against
            the active show folder
        name: Sequence file name without .xsq (default: the song's file name)
        timing_tracks: Any of "Beats" (labelled with the beat's position in its bar), "Bars"
            (numbered), "Drums", "Bass", "Instruments" (stem onsets; need stem separation).
            Effects can reference them, e.g. E_CHOICE_VUMeter_TimingTrack=Beats.
        overwrite: Replace an existing .xsq with the same name
        validate_only: Run every check and return the report without writing
    """
    from xlights_mcp.sequencer.plan_writer import write_plan
    from xlights_mcp.xlights.version import installed_xlights_version

    config = get_config()
    show_path = _active_show(config)
    if isinstance(show_path, dict):
        return show_path
    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}
    if (plan is None) == (plan_path is None):
        return {"error": "Pass exactly one of plan or plan_path."}
    if plan_path is not None:
        plan_file = _show_file(show_path, plan_path)
        try:
            plan = json.loads(plan_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            return {"error": f"Could not read plan file {plan_file}: {e}"}
        if not isinstance(plan, list):
            return {"error": f"Plan file {plan_file} must hold a list of placements."}

    analysis = await _analyze_in_thread(path, ctx)
    return await anyio.to_thread.run_sync(
        lambda: write_plan(
            plan,
            analysis,
            path,
            show_path,
            name=name,
            timing_tracks=timing_tracks or [],
            overwrite=overwrite,
            validate_only=validate_only,
            xlights_version=installed_xlights_version(show_path),
        )
    )


@mcp.tool()
async def preview_plan(
    mp3_path: str, ctx: Context, mode: str = "auto", show_name: str | None = None
) -> dict:
    """Preview the sequence generation plan without creating a file.

    Shows what effects would be placed on which models, based on the
    audio analysis and selected mode.

    Args:
        mp3_path: Path to the .mp3 file
        mode: Generation mode — "auto", "guided", or "template"
        show_name: Which show folder to preview against. If omitted and multiple
            shows exist, returns available shows so you can ask the user.
    """
    from xlights_mcp.sequencer.engine import preview_sequence_plan

    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    config = get_config()
    show_path = _resolve_show(config, show_name)
    if isinstance(show_path, dict):
        return show_path

    on_progress = _progress_forwarder(ctx)
    return await anyio.to_thread.run_sync(
        lambda: preview_sequence_plan(
            mp3_path=path,
            show_path=show_path,
            mode=mode,
            audio_config=config.audio,
            progress=on_progress,
        )
    )


# ---------------------------------------------------------------------------
# Sequence Remapping Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def remap_sequence(
    import_path: str,
    overrides: dict[str, str] | None = None,
    pixel_threshold: float = 0.70,
    show_name: str | None = None,
) -> dict:
    """Import a sequence from a different show layout and remap it to your models.

    Accepts a .xsq file or .zip package from the xLights community. Automatically
    matches imported models to your show's models using name similarity, model type,
    and pixel count. Generates a new .xsq with effects remapped to your layout.

    Args:
        import_path: Path to the .xsq or .zip file to import.
        overrides: Optional dict mapping imported model names to your model names.
            These take precedence over automatic matching.
        pixel_threshold: Similarity threshold for pixel count matching (0.0-1.0).
            Default 0.70 means models must have at least 70% pixel count similarity.
        show_name: Which show folder to import into (e.g., "christmas", "halloween").
            If omitted and multiple shows exist, returns available shows so you can
            ask the user which one to use.

    Returns:
        Dict with mapping report, output path, and summary statistics.
    """
    from xlights_mcp.remapper.generator import generate_remapped_sequence
    from xlights_mcp.remapper.importer import import_package
    from xlights_mcp.remapper.matcher import (
        build_candidates_from_import,
        build_candidates_from_user_show,
        match_models,
    )
    from xlights_mcp.remapper.models import RemapResult
    from xlights_mcp.xlights.show import load_show_config

    import_file = Path(import_path).expanduser()

    # Validate import file
    if not import_file.exists():
        return RemapResult(
            success=False, error=f"File not found: {import_file}"
        ).model_dump()

    ext = import_file.suffix.lower()
    if ext not in (".xsq", ".zip"):
        return RemapResult(
            success=False,
            error=f"Unsupported file type: {ext}. Use .xsq or .zip.",
        ).model_dump()

    # Resolve show folder
    config = get_config()
    show_result = _resolve_show(config, show_name)
    if isinstance(show_result, dict):
        return show_result
    show_path = show_result

    try:
        show_config = load_show_config(show_path)
    except Exception as e:
        return RemapResult(
            success=False, error=f"Failed to load show config: {e}"
        ).model_dump()

    if not show_config.models and not show_config.model_groups:
        return RemapResult(
            success=False, error="No models found in user's active show."
        ).model_dump()

    # Import the sequence
    try:
        seq_data, lxml_root, imported_meta, extracted_assets = import_package(
            import_file, show_path
        )
    except Exception as e:
        return RemapResult(
            success=False, error=str(e)
        ).model_dump()

    if not seq_data.model_names:
        return RemapResult(
            success=False, error="Imported sequence contains no models with effects."
        ).model_dump()

    # Build candidates
    user_candidates = build_candidates_from_user_show(
        show_config.models, show_config.model_groups
    )
    imported_candidates = build_candidates_from_import(
        seq_data.model_names, imported_meta
    )

    # Run matching
    report = match_models(
        imported_candidates=imported_candidates,
        user_candidates=user_candidates,
        threshold=pixel_threshold,
        overrides=overrides or {},
        imported_source=str(import_file),
        has_imported_metadata=imported_meta is not None,
        timing_tracks_preserved=len(seq_data.timing_track_names),
        extracted_assets=extracted_assets,
    )

    # Generate remapped .xsq
    try:
        output_path, missing_assets, asset_warnings = generate_remapped_sequence(
            root=lxml_root,
            report=report,
            show_folder=show_path,
        )
    except Exception as e:
        return RemapResult(
            success=False, error=f"Failed to generate remapped sequence: {e}"
        ).model_dump()

    # Enrich report with post-generation info
    report.missing_assets = missing_assets
    report.warnings.extend(asset_warnings)

    return RemapResult(
        success=True,
        output_path=str(output_path),
        mapping_report=report,
    ).model_dump()


@mcp.prompt()
def sequence_song(mp3_path: str, reference_sequence: str | None = None) -> str:
    """Plan and write a hand-made-style sequence for a song using the show's groups."""
    from xlights_mcp.prompts import render_sequence_song
    from xlights_mcp.xlights.xsq_reader import latest_hand_made_sequence

    show_path = get_config().active_show_path
    reference, notes = reference_sequence, None
    if show_path and show_path.exists():
        if not reference:
            latest = latest_hand_made_sequence(show_path)
            reference = latest.name if latest else None
        notes_file = show_path / ".claude" / "CLAUDE.md"
        if notes_file.is_file():
            try:
                notes = notes_file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                notes = None
    return render_sequence_song(mp3_path, reference, notes)


# ---------------------------------------------------------------------------
# FPP Integration Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def fpp_status() -> dict:
    """Check Falcon Pi Player connection status and current state.

    Returns FPP version, current playlist, scheduler state, etc.
    """
    from xlights_mcp.fpp.client import get_fpp_status

    config = get_config()
    return get_fpp_status(config.fpp)


@mcp.tool()
def fpp_upload_sequence(fseq_path: str, audio_path: str | None = None) -> dict:
    """Upload a sequence (.fseq) and optional audio to Falcon Pi Player.

    Args:
        fseq_path: Path to the .fseq file to upload
        audio_path: Optional path to the audio file (.mp3/.ogg)
    """
    from xlights_mcp.fpp.upload import upload_sequence

    config = get_config()
    return upload_sequence(config.fpp, Path(fseq_path), Path(audio_path) if audio_path else None)


@mcp.tool()
def fpp_list_playlists() -> dict:
    """List all playlists on the Falcon Pi Player."""
    from xlights_mcp.fpp.client import list_playlists

    config = get_config()
    return list_playlists(config.fpp)


@mcp.tool()
def fpp_start_playlist(playlist_name: str, repeat: bool = False) -> dict:
    """Start a playlist on the Falcon Pi Player.

    Args:
        playlist_name: Name of the playlist to start
        repeat: Whether to loop the playlist
    """
    from xlights_mcp.fpp.client import start_playlist

    config = get_config()
    return start_playlist(config.fpp, playlist_name, repeat)


@mcp.tool()
def fpp_stop() -> dict:
    """Stop current playback on the Falcon Pi Player."""
    from xlights_mcp.fpp.client import stop_playback

    config = get_config()
    return stop_playback(config.fpp)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _preload_audio_stack() -> None:
    """Load every native library the analysis pipeline needs before the stdio loop starts.

    On Windows, numpy/scipy's OpenBLAS DLL initializer takes a C-runtime lock that the
    MCP stdin reader thread holds while blocked in read(). Importing those libraries
    lazily inside a tool call therefore deadlocks the server. Running a tiny analysis
    up front forces all DLL loads and numba JIT compilation onto the main thread while
    it is still the only thread.
    """
    started = time.monotonic()
    try:
        import numpy as np
        import soundfile as sf

        from xlights_mcp.audio.beats import detect_beats
        from xlights_mcp.audio.spectrum import analyze_spectrum
        from xlights_mcp.audio.structure import detect_structure

        try:
            import madmom.features.downbeats  # noqa: F401
        except Exception as e:  # noqa: BLE001 - a broken madmom install must not abort warm-up
            logger.debug(f"madmom unavailable, skipping preload: {e}")

        try:
            import demucs.separate  # noqa: F401
            import torch  # noqa: F401
        except Exception as e:  # noqa: BLE001 - a broken demucs/torch install must not abort warm-up
            logger.debug(f"demucs/torch unavailable, skipping preload: {e}")

        sr = 22050
        t = np.arange(sr * 6) / sr
        clicks = (np.sin(2 * np.pi * 440 * t) * (np.sin(2 * np.pi * 2 * t) > 0.95)).astype(np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "warmup.wav"
            sf.write(wav, clicks, sr)
            detect_beats(wav, sr=sr)
            analyze_spectrum(wav, sr=sr)
            detect_structure(wav, sr=sr)
        logger.info(f"Audio stack preloaded in {time.monotonic() - started:.1f}s")
    except Exception as e:
        logger.warning(f"Audio stack preload failed (analysis may be slow or hang on Windows): {e}")


def main():
    """Run the xLights MCP server."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting xLights MCP Server v0.1.0")

    # Ensure config is loaded at startup
    config = get_config()
    logger.info(f"Active show: {config.active_show}")
    logger.info(f"Show path: {config.active_show_path}")

    _preload_audio_stack()
    mcp.run()


if __name__ == "__main__":
    main()
