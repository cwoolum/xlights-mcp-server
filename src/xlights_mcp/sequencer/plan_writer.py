"""Validate an effect plan and write it as an .xsq (the internals behind write_sequence)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from xlights_mcp.audio.analyzer import SongAnalysis
from xlights_mcp.sequencer.plan import validate_plan
from xlights_mcp.sequencer.timing import build_timing_tracks
from xlights_mcp.xlights.effects import known_effect_names
from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.show import load_show_config
from xlights_mcp.xlights.version import installed_xlights_version
from xlights_mcp.xlights.xsq_writer import SequenceSpec, TimingTrack, write_xsq

MAX_REPORTED_ERRORS = 50
_XSQ_SUFFIX = re.compile(r"\.xsq$", re.IGNORECASE)
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def write_plan(
    plan: list,
    analysis: SongAnalysis,
    mp3_path: Path,
    show_path: Path,
    name: str | None = None,
    timing_tracks: Sequence[str] = (),
    extra_tracks: Sequence[TimingTrack] = (),
    overwrite: bool = False,
    validate_only: bool = False,
    show: ShowConfig | None = None,
) -> dict:
    show = show or load_show_config(show_path)
    validated = validate_plan(plan, show, analysis.duration_ms, known_effect_names(show_path))
    tracks, track_warnings, errors = build_timing_tracks(timing_tracks, analysis)
    tracks = [*tracks, *extra_tracks]
    errors = validated.errors + errors
    errors += [
        f"timing track {track!r} appears more than once"
        for track, n in Counter(t.name for t in tracks).items() if n > 1
    ]
    element_names = show.element_names
    errors += [
        f"timing track {t.name!r} has the same name as a model or group in the show"
        for t in tracks if t.name in element_names
    ]

    stem = _XSQ_SUFFIX.sub("", name) if name is not None else mp3_path.stem
    file_name = f"{stem}.xsq"
    name_error = _name_error(name, stem)
    output = None if name_error else show_path / file_name
    if name_error:
        errors.append(name_error)
    elif output.exists() and not overwrite:
        errors.append(f"{file_name} already exists; pass overwrite=true to replace it")

    placements = validated.placements
    report = {
        "path": str(output) if output else None,
        "written": False,
        "elements": len({p.model_name for p in placements}),
        "effects": len(placements),
        "max_layer": max((p.layer for p in placements), default=0),
        "timing_tracks": [t.name for t in tracks],
        "adjusted": validated.adjusted,
        "errors": _capped(errors),
        "warnings": validated.warnings + track_warnings,
    }
    if errors or validate_only:
        return report

    spec = SequenceSpec(
        song_title=mp3_path.stem,
        media_file=str(mp3_path),
        duration_ms=analysis.duration_ms,
        xlights_version=installed_xlights_version(show_path),
        effects=placements,
        timing_tracks=tracks,
    )
    write_xsq(spec, show, output)
    report["written"] = True
    return report


def _name_error(name: str | None, stem: str) -> str | None:
    if name is None:
        return None
    if not stem.strip(" .") or "/" in stem or "\\" in stem:
        return f"name must be a file name without folders, got {name!r}"
    bad = _INVALID_NAME_CHARS.search(stem)
    if bad:
        return f"name contains a character Windows doesn't allow in file names ({bad.group()!r}), got {name!r}"
    return None


def _capped(errors: list[str]) -> list[str]:
    if len(errors) <= MAX_REPORTED_ERRORS:
        return errors
    return [*errors[:MAX_REPORTED_ERRORS], f"... and {len(errors) - MAX_REPORTED_ERRORS} more errors"]
