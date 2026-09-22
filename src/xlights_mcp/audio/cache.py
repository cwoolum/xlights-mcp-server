"""On-disk cache for full song analysis results.

Keyed by a hash of the audio file's bytes plus ANALYSIS_VERSION, so edits to the
audio or to the analysis pipeline both invalidate stale entries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xlights_mcp.audio.analyzer import SongAnalysis

logger = logging.getLogger(__name__)

# Bump when the analysis pipeline changes in a way that makes old results stale.
ANALYSIS_VERSION = 3


def file_content_hash(path: Path) -> str:
    """SHA1 hex digest of a file's raw bytes."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_key(audio_path: Path) -> str:
    """Content hash of the audio file, combined with the analysis version."""
    h = hashlib.sha1()
    h.update(f"v{ANALYSIS_VERSION}:".encode())
    h.update(file_content_hash(audio_path).encode())
    return h.hexdigest()


def cache_path(audio_path: Path, cache_dir: Path) -> Path:
    return cache_dir / "analysis" / f"{cache_key(audio_path)}.json"


def load_cached(audio_path: Path, cache_dir: Path) -> SongAnalysis | None:
    """Return the cached analysis for this file, or None if absent/unreadable."""
    from xlights_mcp.audio.analyzer import SongAnalysis

    path = cache_path(audio_path, cache_dir)
    if not path.exists():
        return None
    try:
        analysis = SongAnalysis.model_validate_json(path.read_text())
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Ignoring unreadable analysis cache {path}: {e}")
        return None
    analysis.cached = True
    return analysis


def save_cached(analysis: SongAnalysis, audio_path: Path, cache_dir: Path) -> Path:
    """Persist an analysis result. Returns the cache file path.

    Written atomically (temp file + os.replace) so a reader never observes a
    partially written file, and a failed write can't corrupt an existing entry.
    """
    path = cache_path(audio_path, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(analysis.model_dump_json())
        os.replace(tmp_name, path)
    except BaseException:
        os.remove(tmp_name)
        raise
    return path
