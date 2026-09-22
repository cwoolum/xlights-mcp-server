"""Full audio analysis pipeline — combines all analysis modules."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import librosa
import numpy as np
from pydantic import BaseModel, Field

from xlights_mcp.audio.beats import BeatMap, detect_beats
from xlights_mcp.audio.cache import load_cached, save_cached
from xlights_mcp.audio.drums import find_silences
from xlights_mcp.audio.separator import StemPaths, separate_stems
from xlights_mcp.audio.spectrum import SpectrumAnalysis, analyze_spectrum
from xlights_mcp.audio.stems_model import StemAnalysis, StemOnsets
from xlights_mcp.audio.structure import SongSection, detect_structure
from xlights_mcp.config import AudioConfig

logger = logging.getLogger(__name__)


class SongAnalysis(BaseModel):
    """Complete analysis of a music file for sequence generation."""

    file_path: str
    file_name: str
    duration_seconds: float = 0.0
    beats: BeatMap = Field(default_factory=BeatMap)
    spectrum: SpectrumAnalysis = Field(default_factory=SpectrumAnalysis)
    sections: list[SongSection] = Field(default_factory=list)
    stems: StemPaths = Field(default_factory=StemPaths)
    stem_analysis: StemAnalysis = Field(default_factory=StemAnalysis)
    cached: bool = False  # True when served from the on-disk analysis cache

    @property
    def duration_ms(self) -> int:
        return int(self.duration_seconds * 1000)


ProgressCallback = Callable[[int, int, str], None]
"""Called as (completed_stages, total_stages, message) at each stage boundary."""

_STAGE_COUNT = 5


def full_analysis(
    audio_path: Path,
    audio_config: AudioConfig | None = None,
    progress: ProgressCallback | None = None,
    force: bool = False,
) -> SongAnalysis:
    """Run the complete audio analysis pipeline.

    Source separation (Demucs) is always attempted; it's a no-op returning
    StemPaths(available=False) when the optional dependency isn't installed.

    Results are cached on disk (keyed by file content); a cache hit returns
    immediately with ``cached=True``.

    Args:
        audio_path: Path to the audio file (.mp3, .wav, etc.)
        audio_config: Audio configuration settings
        progress: Optional callback invoked at each stage boundary
        force: Re-run analysis even if a cached result exists
    """
    if audio_config is None:
        audio_config = AudioConfig()

    def report(done: int, message: str) -> None:
        logger.info(f"[{done}/{_STAGE_COUNT}] {message}")
        if progress:
            progress(done, _STAGE_COUNT, message)

    if not force:
        cached = load_cached(audio_path, audio_config.cache_dir)
        if cached is not None:
            report(_STAGE_COUNT, "Loaded cached analysis")
            return cached

    sr = audio_config.sample_rate
    logger.info(f"Starting full analysis: {audio_path}")

    report(0, "Analyzing spectrum and energy")
    spectrum = analyze_spectrum(audio_path, sr=sr)

    report(1, "Separating stems")
    stems = StemPaths()
    stem_analysis = StemAnalysis()
    stem_pipeline_failed = False
    try:
        stems = separate_stems(audio_path)
        if stems.available:
            report(2, "Analyzing stems")
            stem_analysis = analyze_stems(stems, sr=sr)
    except Exception as e:  # noqa: BLE001 - stem separation/analysis can fail many ways; must not abort
        logger.warning(f"Stem separation/analysis failed, continuing without stems: {e}")
        stem_pipeline_failed = True

    if stems.failed:
        # separate_stems itself caught a real separation failure (its own
        # try/except returns normally rather than raising) -- degraded, not the
        # stable "Demucs isn't installed" outcome, so don't cache it.
        stem_pipeline_failed = True
    elif stems.available and not stem_analysis.available:
        # Separation succeeded but analyze_stems's per-stem try/except swallowed
        # every stem's failure and also returned normally -- same deal.
        stem_pipeline_failed = True

    drums = stem_analysis.stems.get("drums") if stem_analysis.available else None
    report(3, "Detecting beats and tempo")
    beats = detect_beats(audio_path, sr=sr, drums=drums)
    report(4, "Detecting song structure")
    sections = detect_structure(audio_path, sr=sr, drums=drums, beats=beats)

    analysis = SongAnalysis(
        file_path=str(audio_path),
        file_name=audio_path.name,
        duration_seconds=spectrum.duration_seconds,
        beats=beats,
        spectrum=spectrum,
        sections=sections,
        stems=stems,
        stem_analysis=stem_analysis,
    )

    logger.info(
        f"Analysis complete: {analysis.duration_seconds:.1f}s, "
        f"{beats.tempo:.0f} BPM, "
        f"{len(sections)} sections, "
        f"{len(beats.beat_times)} beats, "
        f"stems={'yes' if stem_analysis.available else 'no'}"
    )

    if stem_pipeline_failed:
        logger.warning(
            "Not caching this result because stem separation/analysis failed; "
            "a later call will retry it."
        )
    else:
        save_cached(analysis, audio_path, audio_config.cache_dir)
    report(_STAGE_COUNT, "Analysis complete")
    return analysis


def analyze_stems(stem_paths: StemPaths, sr: int = 22050) -> StemAnalysis:
    """Run onset detection and energy analysis on separated stems.

    Args:
        stem_paths: Paths to the Demucs-separated stem .wav files
        sr: Sample rate for analysis
    """
    stem_map = {
        "drums": stem_paths.drums,
        "bass": stem_paths.bass,
        "other": stem_paths.other,
        "vocals": stem_paths.vocals,
    }

    results: dict[str, StemOnsets] = {}

    for name, path_str in stem_map.items():
        if not path_str:
            continue
        stem_path = Path(path_str)
        if not stem_path.exists():
            continue

        try:
            y, loaded_sr = librosa.load(str(stem_path), sr=sr, mono=True)

            # Onset detection
            onset_env = librosa.onset.onset_strength(y=y, sr=loaded_sr)
            onset_frames = librosa.onset.onset_detect(
                onset_envelope=onset_env, sr=loaded_sr, backtrack=True
            )
            onset_times = librosa.frames_to_time(onset_frames, sr=loaded_sr).tolist()
            # Only the drums stem needs kick/pickup discrimination (see drums.py);
            # skip the extra STFT for the other three stems.
            onset_bass = _onset_bass_levels(y, loaded_sr, onset_times) if name == "drums" else []

            # RMS energy curve
            rms = librosa.feature.rms(y=y)[0]
            rms_times = librosa.times_like(rms, sr=loaded_sr).tolist()
            max_rms = float(rms.max()) + 1e-8
            normalized_rms = (rms / max_rms).tolist()
            mean_energy = float(np.mean(rms / max_rms))

            results[name] = StemOnsets(
                name=name,
                onset_times=onset_times,
                onset_bass=onset_bass,
                energy=normalized_rms,
                energy_times=rms_times,
                mean_energy=mean_energy,
                silences=find_silences(
                    np.asarray(normalized_rms), np.asarray(rms_times), end=len(y) / loaded_sr
                ),
            )
            logger.info(f"  Stem '{name}': {len(onset_times)} onsets, mean energy {mean_energy:.2f}")

        except Exception as e:
            logger.warning(f"Failed to analyze stem '{name}': {e}")

    if results:
        logger.info(f"Stem analysis complete: {list(results.keys())}")
        return StemAnalysis(available=True, stems=results)

    return StemAnalysis(available=False)


_KICK_BAND_HZ = 150
_ONSET_BASS_WINDOW = (-0.02, 0.12)  # seconds around each onset to search for its peak


def _onset_bass_levels(y: np.ndarray, sr: int, onset_times: list[float]) -> list[float]:
    """Peak low-frequency (<150 Hz) level just after each onset, normalised 0-1 over the stem.

    Used to tell a kick (strong low end) from a kickless pickup hit (hi-hat/snare,
    little low end) at the same onset time.
    """
    stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low = stft[freqs < _KICK_BAND_HZ].sum(axis=0)
    max_low = low.max() if low.size else 0.0
    if max_low > 0:
        low = low / max_low
    frame_times = librosa.frames_to_time(np.arange(len(low)), sr=sr, hop_length=512)

    before, after = _ONSET_BASS_WINDOW
    levels = []
    for onset in onset_times:
        window = (frame_times >= onset + before) & (frame_times < onset + after)
        levels.append(round(float(low[window].max()), 3) if np.any(window) else 0.0)
    return levels
