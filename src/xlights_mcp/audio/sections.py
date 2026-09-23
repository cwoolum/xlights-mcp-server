"""Song section model and the label vocabulary shared by structure detection and the engine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SECTION_LABELS: tuple[str, ...] = (
    "intro", "build", "drop", "breakdown", "outro",
    "verse", "chorus", "bridge", "transition", "instrumental",
)


class SongSection(BaseModel):
    """A detected section of a song."""

    label: str  # see SECTION_LABELS; the mixdown labeller may also emit "unknown" placeholders
    start_time: float  # seconds
    end_time: float  # seconds
    energy_level: float = 0.0  # 0.0-1.0 average energy
    confidence: float = 0.0
    structure_source: Literal["stems", "mixdown"] = "mixdown"
    drums: Literal["present", "absent", "decaying"] | None = None

    @property
    def start_time_ms(self) -> int:
        return int(self.start_time * 1000)

    @property
    def end_time_ms(self) -> int:
        return int(self.end_time * 1000)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
