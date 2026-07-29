"""Presentation-neutral read models for background-run monitoring."""

from dataclasses import dataclass
from datetime import datetime

from job_application_copilot.domain.background_task import (
    BackgroundOperation,
    BackgroundTaskStatus,
)


@dataclass(frozen=True, slots=True)
class BackgroundRunFilters:
    """Optional exact filters for the Background Runs screen."""

    operation: BackgroundOperation | None = None
    status: BackgroundTaskStatus | None = None
    batch_id: int | None = None
    job_id: int | None = None


@dataclass(frozen=True, slots=True)
class BackgroundAttemptSummary:
    """Retained values for one execution attempt."""

    attempt_number: int
    status: BackgroundTaskStatus
    pipeline_step: str | None
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class BackgroundRunSummary:
    """One logical job task and all retained execution attempts."""

    task_id: int
    batch_id: int
    batch_created_at: datetime
    job_id: int
    company: str
    job_title: str
    operation: BackgroundOperation
    status: BackgroundTaskStatus
    retry_count: int
    pipeline_step: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    attempts: tuple[BackgroundAttemptSummary, ...]

    @property
    def retryable(self) -> bool:
        """Return whether manual retry is valid for this task."""

        return self.status in {
            BackgroundTaskStatus.FAILED,
            BackgroundTaskStatus.INTERRUPTED,
        }

    @property
    def active(self) -> bool:
        """Return whether the UI should continue polling this task."""

        return self.status in {
            BackgroundTaskStatus.PENDING,
            BackgroundTaskStatus.RUNNING,
        }
