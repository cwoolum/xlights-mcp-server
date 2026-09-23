"""Tests for stem-directory caching keyed by the source audio's content hash.

Stems are cached by file name (see separate_stems); if the audio behind that
name changes, a sidecar hash file is what tells us the cached stems are stale.
Demucs itself is stubbed out (see demucs_fixtures) so these tests never invoke
the real model.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from demucs_fixtures import install_fake_demucs

from xlights_mcp.audio.cache import file_content_hash
from xlights_mcp.audio.separator import separate_stems


def _write_wav(path: Path, value: float) -> None:
    sr = 22050
    y = np.ones(sr, dtype=np.float32) * value
    sf.write(path, y, sr)


def _sidecar_for(audio_path: Path) -> Path:
    return audio_path.parent / "stems" / audio_path.stem / "source.sha1"


def test_separate_stems_reuses_cache_when_source_hash_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[Path] = []
    install_fake_demucs(monkeypatch, calls)
    audio_path = tmp_path / "song.wav"
    _write_wav(audio_path, 0.1)

    first = separate_stems(audio_path)
    second = separate_stems(audio_path)

    assert len(calls) == 1
    assert first.available and second.available
    assert second.vocals == first.vocals
    assert _sidecar_for(audio_path).read_text().strip() == file_content_hash(audio_path)


def test_separate_stems_reseparates_when_sidecar_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[Path] = []
    install_fake_demucs(monkeypatch, calls)
    audio_path = tmp_path / "song.wav"
    _write_wav(audio_path, 0.1)

    separate_stems(audio_path)
    _sidecar_for(audio_path).unlink()

    separate_stems(audio_path)

    assert len(calls) == 2
    assert _sidecar_for(audio_path).exists()


def test_separate_stems_reseparates_when_source_content_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[Path] = []
    install_fake_demucs(monkeypatch, calls)
    audio_path = tmp_path / "song.wav"
    _write_wav(audio_path, 0.1)

    separate_stems(audio_path)
    _write_wav(audio_path, 0.9)  # same name, different content

    separate_stems(audio_path)

    assert len(calls) == 2
    assert _sidecar_for(audio_path).read_text().strip() == file_content_hash(audio_path)


def test_separate_stems_marks_failed_when_demucs_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def boom(_path: str):
        raise RuntimeError("CUDA out of memory")

    install_fake_demucs(monkeypatch, separate=boom)
    audio_path = tmp_path / "song.wav"
    _write_wav(audio_path, 0.1)

    stems = separate_stems(audio_path)

    assert stems.available is False
    assert stems.failed is True


def test_separate_stems_not_installed_is_not_marked_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import sys

    # Simulate demucs genuinely not being importable, distinct from it being
    # importable but failing during separation.
    monkeypatch.setitem(sys.modules, "demucs", None)
    audio_path = tmp_path / "song.wav"
    _write_wav(audio_path, 0.1)

    stems = separate_stems(audio_path)

    assert stems.available is False
    assert stems.failed is False


def test_broken_torch_import_counts_as_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import builtins

    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "torch":
            raise OSError("[WinError 126] fbgemm.dll could not be loaded")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    audio = tmp_path / "song.wav"
    sf.write(audio, np.zeros(22050, dtype=np.float32), 22050)

    stems = separate_stems(audio)

    assert stems.available is False
    assert stems.failed is False
