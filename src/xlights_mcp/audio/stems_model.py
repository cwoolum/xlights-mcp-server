"""Per-stem onset/energy models, kept free of other audio-module imports."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field


class StemOnsets(BaseModel):
    """Onset and energy analysis for a single audio stem."""

    name: str  # "drums", "bass", "other", "vocals"
    onset_times: list[float] = Field(default_factory=list)  # seconds
    energy: list[float] = Field(default_factory=list)  # normalized 0-1 per frame
    energy_times: list[float] = Field(default_factory=list)  # seconds
    mean_energy: float = 0.0
    silences: list[tuple[float, float]] = Field(default_factory=list)  # seconds, [start, end)


class StemAnalysis(BaseModel):
    """Onset and energy analysis for all separated stems."""

    available: bool = False
    stems: dict[str, StemOnsets] = Field(default_factory=dict)  # name → StemOnsets

    def get_onsets_in_range(self, stem: str, start: float, end: float) -> list[float]:
        """Get onset times for a stem within a time range."""
        if stem not in self.stems:
            return []
        return [t for t in self.stems[stem].onset_times if start <= t < end]

    def get_mean_energy_in_range(self, stem: str, start: float, end: float) -> float:
        """Get mean energy for a stem within a time range."""
        if stem not in self.stems:
            return 0.0
        s = self.stems[stem]
        energies = [e for t, e in zip(s.energy_times, s.energy) if start <= t < end]
        return float(np.mean(energies)) if energies else 0.0

    def dominant_stem(self, start: float, end: float) -> str:
        """Return the stem name with highest mean energy in a time range."""
        best_name = "other"
        best_energy = 0.0
        for name in self.stems:
            e = self.get_mean_energy_in_range(name, start, end)
            if e > best_energy:
                best_energy = e
                best_name = name
        return best_name
