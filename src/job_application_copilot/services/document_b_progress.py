"""Progress events for a user-triggered Document B processing operation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentBProcessingProgress:
    """One safe, presentation-neutral update from Document B processing."""

    stage: str
    message: str
    completed_sections: int | None = None
    total_sections: int | None = None


DocumentBProgressReporter = Callable[[DocumentBProcessingProgress], None]
