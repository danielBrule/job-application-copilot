"""Domain types and lifecycle rules for durable background work."""

from collections.abc import Mapping
from enum import StrEnum


class BackgroundOperation(StrEnum):
    """The single operation represented by a background batch."""

    ASSESSMENT = "ASSESSMENT"
    CV_GENERATION = "CV_GENERATION"


class BackgroundTaskStatus(StrEnum):
    """Lifecycle states for one independently processed background task."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


ALLOWED_BACKGROUND_TASK_TRANSITIONS: Mapping[
    BackgroundTaskStatus, frozenset[BackgroundTaskStatus]
] = {
    BackgroundTaskStatus.PENDING: frozenset({BackgroundTaskStatus.RUNNING}),
    BackgroundTaskStatus.RUNNING: frozenset(
        {
            BackgroundTaskStatus.COMPLETED,
            BackgroundTaskStatus.FAILED,
            BackgroundTaskStatus.INTERRUPTED,
        }
    ),
    BackgroundTaskStatus.FAILED: frozenset({BackgroundTaskStatus.PENDING}),
    BackgroundTaskStatus.INTERRUPTED: frozenset({BackgroundTaskStatus.PENDING}),
    BackgroundTaskStatus.COMPLETED: frozenset(),
}


def is_valid_background_task_transition(
    current: BackgroundTaskStatus,
    target: BackgroundTaskStatus,
) -> bool:
    """Return whether a task lifecycle transition is explicitly permitted."""

    return target in ALLOWED_BACKGROUND_TASK_TRANSITIONS[current]
