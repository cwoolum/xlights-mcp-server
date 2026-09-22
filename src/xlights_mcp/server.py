"""MCP Server entry point for xLights Sequence Generator."""

from __future__ import annotations

import logging
import tempfile
import time
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
def list_models() -> dict:
    """List all light models in the active xLights show.

    Returns model names, types, controller assignments, and channel info.
    """
    from xlights_mcp.xlights.show import load_show_models

    config = get_config()
    show_path = config.active_show_path
    if not show_path or not show_path.exists():
        return {
            "error": "No active show folder configured.",
            "action_required": "Ask the user for the path to their xLights show directory and call add_show_folder.",
        }

    models = load_show_models(show_path)
    return {
        "show": config.active_show,
        "model_count": len(models),
        "models": [m.model_dump() for m in models],
    }


@mcp.tool()
def list_controllers() -> dict:
    """List all controllers configured in the active xLights show.

    Returns controller names, IPs, protocols, and channel counts.
    """
    from xlights_mcp.xlights.show import load_show_controllers

    config = get_config()
    show_path = config.active_show_path
    if not show_path or not show_path.exists():
        return {
            "error": "No active show folder configured.",
            "action_required": "Ask the user for the path to their xLights show directory and call add_show_folder.",
        }

    controllers = load_show_controllers(show_path)
    return {
        "show": config.active_show,
        "controller_count": len(controllers),
        "controllers": [c.model_dump() for c in controllers],
    }


@mcp.tool()
def list_sequences() -> dict:
    """List all sequences (.xsq files) in the active show folder."""
    config = get_config()
    show_path = config.active_show_path
    if not show_path or not show_path.exists():
        return {
            "error": "No active show folder configured.",
            "action_required": "Ask the user for the path to their xLights show directory and call add_show_folder.",
        }

    sequences = []
    for xsq in sorted(show_path.glob("*.xsq")):
        sequences.append({"name": xsq.stem, "path": str(xsq)})
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

    config = get_config()
    show_path = config.active_show_path
    if not show_path:
        return {"error": "No active show configured"}

    xsq_path = show_path / f"{sequence_name}.xsq"
    if not xsq_path.exists():
        return {"error": f"Sequence not found: {xsq_path}"}

    return read_xsq_summary(xsq_path)


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


async def _analyze_in_thread(path: Path, ctx: Context, force: bool = False):
    """Run full_analysis off the event loop, forwarding stage progress to the client."""
    from xlights_mcp.audio.analyzer import full_analysis

    config = get_config()
    on_progress = _progress_forwarder(ctx)
    return await anyio.to_thread.run_sync(
        lambda: full_analysis(path, config.audio, progress=on_progress, force=force)
    )


@mcp.tool()
async def analyze_song(mp3_path: str, ctx: Context, force: bool = False) -> dict:
    """Analyze a music file for light show sequencing.

    Performs full audio analysis: beat detection, song structure,
    frequency spectrum, energy profile, and optionally source separation.
    Progress is streamed as MCP progress notifications while it runs.

    Results are cached on disk keyed by file content, so repeat calls (and
    create_sequence on the same file) return instantly. Returns a compact
    summary; use get_beat_map / get_energy_profile / get_song_structure / get_stem_events for
    detailed data.

    The response also includes: stems is a per-stem summary
    {onsets, mean_energy, silences_ms} keyed by "drums"/"bass"/"vocals"/"other", or
    null when source separation is unavailable — in that case get_stem_events will
    also return an error. sections[].drums is "present"/"absent"/"decaying", or null
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
    """Get the verse/chorus/bridge structure of a song.

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

    kind="silences": [start, end] ms spans where the stem is silent, clipped to the
    window. Returns {"spans_ms": [[start, end], ...]} and is never truncated. For
    drums, a silence marks a breakdown, riser, or other gap; the span's END is where
    the drums come back in (e.g. a drop).

    onsets and energy return at most max_events items; when the response has
    truncated=true, call again with start_ms=next_start_ms to continue. An invalid
    stem, kind, resolution, max_events, or window (start_ms > end_ms) returns
    {"error": ...} without analysing.

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

    error = validate_stem_query(
        stem, kind, resolution, max_events=max_events, start_ms=start_ms, end_ms=end_ms
    )
    if error:
        return {"error": error}
    path = Path(mp3_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    analysis = await _analyze_in_thread(path, ctx)
    return stem_events(analysis, stem, kind, start_ms, end_ms, max_events, resolution)


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
    """Create an xLights sequence from a music file.

    Analyzes the audio and generates a .xsq file with effects placed on
    your light models according to the selected generation mode.

    Args:
        mp3_path: Path to the .mp3 file
        mode: Generation mode — "auto" (AI picks everything), "guided" (interactive),
              or "template" (apply saved recipes)
        palette_hint: Optional color hint (e.g., "red and green", "orange and purple")
        theme: Optional theme hint (e.g., "christmas", "halloween", "energetic")
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
        except ImportError:
            pass

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
