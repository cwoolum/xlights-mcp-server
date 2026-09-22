"""Tests for stem-directory caching keyed by the source audio's content hash.

Stems are cached by file name (see separate_stems); if the audio behind that
name changes, a sidecar hash file is what tells us the cached stems are stale.
Demucs itself is stubbed out so these tests never invoke the real model.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from xlights_mcp.audio.cache import file_content_hash
from xlights_mcp.audio.separator import separate_stems


def _write_wav(path: Path, value: float) -> None:
    sr = 22050
    y = (np.ones(sr, dtype=np.float32) * value)
    sf.write(path, y, sr)


class _FakeTensor:
    def __init__(self, arr: np.ndarray) -> None:
        self._arr = arr
        self.ndim = arr.ndim

    def cpu(self) -> _FakeTensor:
        return self

    def numpy(self) -> np.ndarray:
        return self._arr


def _install_fake_demucs(monkeypatch: pytest.MonkeyPatch, calls: list[Path]) -> None:
    """Install a fake demucs.api.Separator that records calls instead of separating."""

    class FakeSeparator:
        samplerate = 22050

        def __init__(self, model: str) -> None:
            self.model = model

        def separate_audio_file(self, path: str):
            calls.append(Path(path))
            arr = np.zeros(100, dtype=np.float32)
            stems = {name: _FakeTensor(arr) for name in ("vocals", "drums", "bass", "other")}
            return None, stems

    demucs_mod = types.ModuleType("demucs")
    demucs_separate_mod = types.ModuleType("demucs.separate")
    demucs_api_mod = types.ModuleType("demucs.api")
    demucs_api_mod.Separator = FakeSeparator
    demucs_mod.separate = demucs_separate_mod
    demucs_mod.api = demucs_api_mod
    torch_mod = types.ModuleType("torch")

    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    monkeypatch.setitem(sys.modules, "demucs", demucs_mod)
    monkeypatch.setitem(sys.modules, "demucs.separate", demucs_separate_mod)
    monkeypatch.setitem(sys.modules, "demucs.api", demucs_api_mod)


def _sidecar_for(audio_path: Path) -> Path:
    return audio_path.parent / "stems" / audio_path.stem / "source.sha1"


def test_separate_stems_reuses_cache_when_source_hash_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[Path] = []
    _install_fake_demucs(monkeypatch, calls)
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
    _install_fake_demucs(monkeypatch, calls)
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
    _install_fake_demucs(monkeypatch, calls)
    audio_path = tmp_path / "song.wav"
    _write_wav(audio_path, 0.1)

    separate_stems(audio_path)
    _write_wav(audio_path, 0.9)  # same name, different content

    separate_stems(audio_path)

    assert len(calls) == 2
    assert _sidecar_for(audio_path).read_text().strip() == file_content_hash(audio_path)
