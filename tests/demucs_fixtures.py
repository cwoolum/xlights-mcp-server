"""Fake demucs.api module installer, shared by tests that must never invoke the
real Demucs model (real separation is slow and needs the [separation] extra).

Installs fake `torch`/`demucs`/`demucs.separate`/`demucs.api` entries in
sys.modules, so separate_stems's own `import torch; import demucs.separate`
availability check succeeds and its `import demucs.api` branch runs against
the fake Separator below.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest


class FakeTensor:
    """Stands in for a torch.Tensor: separate_stems only calls .cpu().numpy()."""

    def __init__(self, arr: np.ndarray) -> None:
        self._arr = arr
        self.ndim = arr.ndim

    def cpu(self) -> FakeTensor:
        return self

    def numpy(self) -> np.ndarray:
        return self._arr


def silent_stems() -> dict[str, FakeTensor]:
    arr = np.zeros(100, dtype=np.float32)
    return {name: FakeTensor(arr) for name in ("vocals", "drums", "bass", "other")}


def install_fake_demucs(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[Path] | None = None,
    separate: Callable[[str], tuple[None, dict[str, FakeTensor]]] | None = None,
) -> None:
    """Install a fake demucs.api.Separator so tests never invoke real demucs.

    By default, separate_audio_file records the call (in `calls`, if given) and
    returns silent stems for all four names. Pass `separate` to run something
    else instead -- e.g. one that raises, simulating a real separation failure
    (CUDA OOM, a corrupt model download, ...) rather than "demucs not
    installed".
    """
    calls = calls if calls is not None else []

    class FakeSeparator:
        samplerate = 22050

        def __init__(self, model: str) -> None:
            self.model = model

        def separate_audio_file(self, path: str):
            calls.append(Path(path))
            if separate is not None:
                return separate(path)
            return None, silent_stems()

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
