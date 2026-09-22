"""Synthetic drum stems for tests: onsets every half second inside each run."""

from __future__ import annotations

import numpy as np

from xlights_mcp.audio.drums import find_silences
from xlights_mcp.audio.stems_model import StemOnsets

HOP = 512 / 22050


def make_drum_stem(
    runs: list[tuple[float, float]], duration: float, decay_s: float = 0.0, name: str = "drums"
) -> StemOnsets:
    """Onsets every 0.5 s in each [start, end) run; energy 1.0 through each run,
    then a linear decay over decay_s seconds after the run's last onset."""
    times = np.arange(0, duration, HOP)
    energy = np.zeros_like(times)
    onsets: list[float] = []
    for a, b in runs:
        run_onsets = np.arange(a, b, 0.5)
        onsets.extend(float(t) for t in run_onsets)
        tail = run_onsets[-1] + 0.25
        energy[(times >= a) & (times <= tail)] = 1.0
        if decay_s > 0:
            fading = (times > tail) & (times <= tail + decay_s)
            energy[fading] = np.maximum(energy[fading], 1.0 - (times[fading] - tail) / decay_s)
    return StemOnsets(
        name=name,
        onset_times=onsets,
        energy=energy.tolist(),
        energy_times=times.tolist(),
        mean_energy=float(energy.mean()),
        silences=find_silences(energy, times, end=duration),
    )
