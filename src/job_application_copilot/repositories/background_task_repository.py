"""Session-scoped persistence operations for background batches and tasks."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    BackgroundAttemptSummary,
    BackgroundOperation,
    BackgroundRunFilters,
    BackgroundRunSummary,
    BackgroundTaskStatus,
    is_valid_background_task_transition,
)
from job_application_copilot.errors import ApplicationNotFoundError, ApplicationValidationError
from job_application_copilot.repositories.models import (
    BackgroundBatch,
    BackgroundTask,
    BackgroundTaskAttempt,
    Job,
)
from job_application_copilot.repositories.models.common import utc_now


class BackgroundBatchNotFoundError(ApplicationNotFoundError):
    """Raised when a required background batch does not exist."""

    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        super().__init__(f"Background batch {batch_id} does not exist.")


class BackgroundTaskNotFoundError(ApplicationNotFoundError):
    """Raised when a required background task does not exist."""

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        super().__init__(f"Background task {task_id} does not exist.")


class BackgroundTaskBatchOperationMismatchError(ApplicationValidationError):
    """Raised when task operation differs from its batch operation."""

    def __init__(
        self, batch_operation: BackgroundOperation, task_operation: BackgroundOperation
    ) -> None:
        super().__init__(
            "A background task operation must match its batch operation "
            f"({batch_operation.value} != {task_operation.value})."
        )


class InvalidBackgroundTaskTransitionError(ApplicationValidationError):
    """Raised for a lifecycle transition outside the permitted state graph."""

    def __init__(self, current: BackgroundTaskStatus, target: BackgroundTaskStatus) -> None:
        super().__init__(
            f"Background task cannot transition from {current.value} to {target.value}."
        )


class BackgroundBatchRepository:
    """Read and write background batches within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, batch: BackgroundBatch) -> BackgroundBatch:
        """Persist a new batch and populate generated values."""

        self.session.add(batch)
        self.session.flush()
        return batch

    def get(self, batch_id: int) -> BackgroundBatch | None:
        """Return a batch by identifier, or None when it does not exist."""

        return self.session.get(BackgroundBatch, batch_id)

    def require(self, batch_id: int) -> BackgroundBatch:
        """Return an existing batch or raise an actionable lookup error."""

        batch = self.get(batch_id)
        if batch is None:
            raise BackgroundBatchNotFoundError(batch_id)
        return batch


class BackgroundTaskRepository:
    """Read, create, and transition background tasks in one transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, task: BackgroundTask) -> BackgroundTask:
        """Persist a task after confirming it matches its canonical batch operation."""

        batch = BackgroundBatchRepository(self.session).require(task.batch_id)
        if task.operation is not batch.operation:
            raise BackgroundTaskBatchOperationMismatchError(batch.operation, task.operation)
        self.session.add(task)
        self.session.flush()
        return task

    def get(self, task_id: int) -> BackgroundTask | None:
        """Return a task by identifier, or None when it does not exist."""

        return self.session.get(BackgroundTask, task_id)

    def require(self, task_id: int) -> BackgroundTask:
        """Return an existing task or raise an actionable lookup error."""

        task = self.get(task_id)
        if task is None:
            raise BackgroundTaskNotFoundError(task_id)
        return task

    def list(
        self,
        *,
        batch_id: int | None = None,
        job_id: int | None = None,
        status: BackgroundTaskStatus | None = None,
    ) -> list[BackgroundTask]:
        """Return matching tasks in deterministic oldest-first queue order."""

        statement = select(BackgroundTask)
        if batch_id is not None:
            statement = statement.where(BackgroundTask.batch_id == batch_id)
        if job_id is not None:
            statement = statement.where(BackgroundTask.job_id == job_id)
        if status is not None:
            statement = statement.where(BackgroundTask.status == status)
        statement = statement.order_by(BackgroundTask.created_at.asc(), BackgroundTask.id.asc())
        return list(self.session.scalars(statement))

    def claim_next_pending(
        self,
        operations: Collection[BackgroundOperation],
    ) -> BackgroundTask | None:
        """Claim the oldest pending task for one of the worker's registered operations."""

        if not operations:
            return None

        task = self.session.scalar(
            select(BackgroundTask)
            .where(
                BackgroundTask.status == BackgroundTaskStatus.PENDING,
                BackgroundTask.operation.in_(operations),
            )
            .order_by(BackgroundTask.created_at.asc(), BackgroundTask.id.asc())
            .limit(1)
        )
        if task is None:
            return None
        return self.transition(task, BackgroundTaskStatus.RUNNING)

    def transition(
        self,
        task: BackgroundTask,
        target: BackgroundTaskStatus,
        *,
        error_message: str | None = None,
    ) -> BackgroundTask:
        """Apply one valid lifecycle transition and maintain its durable timestamps."""

        if not is_valid_background_task_transition(task.status, target):
            raise InvalidBackgroundTaskTransitionError(task.status, target)
        if error_message is not None and target not in {
            BackgroundTaskStatus.FAILED,
            BackgroundTaskStatus.INTERRUPTED,
        }:
            raise InvalidBackgroundTaskTransitionError(task.status, target)

        now = utc_now()
        if target is BackgroundTaskStatus.RUNNING:
            task.started_at = now
            task.completed_at = None
            task.error_message = None
            self.session.add(
                BackgroundTaskAttempt(
                    task_id=task.id,
                    attempt_number=task.retry_count + 1,
                    status=BackgroundTaskStatus.RUNNING,
                    pipeline_step=task.pipeline_step,
                    started_at=now,
                )
            )
        elif target in {BackgroundTaskStatus.FAILED, BackgroundTaskStatus.INTERRUPTED}:
            task.completed_at = now
            task.error_message = error_message
            self._finish_active_attempt(task, target, now, error_message)
        elif target is BackgroundTaskStatus.COMPLETED:
            task.completed_at = now
            task.error_message = None
            self._finish_active_attempt(task, target, now, None)
        elif target is BackgroundTaskStatus.PENDING:
            task.retry_count += 1
            task.started_at = None
            task.completed_at = None
            task.error_message = None

        task.status = target
        self.session.flush()
        return task

    def _finish_active_attempt(
        self,
        task: BackgroundTask,
        target: BackgroundTaskStatus,
        completed_at: datetime,
        error_message: str | None,
    ) -> None:
        attempt = self.session.scalar(
            select(BackgroundTaskAttempt)
            .where(
                BackgroundTaskAttempt.task_id == task.id,
                BackgroundTaskAttempt.status == BackgroundTaskStatus.RUNNING,
            )
            .order_by(BackgroundTaskAttempt.attempt_number.desc())
            .limit(1)
        )
        if attempt is None:
            raise InvalidBackgroundTaskTransitionError(task.status, target)
        attempt.status = target
        attempt.pipeline_step = task.pipeline_step
        attempt.completed_at = completed_at
        attempt.error_message = error_message


class BackgroundRunRepository:
    """Read task, batch, job, and attempt history for operational monitoring."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, filters: BackgroundRunFilters | None = None) -> list[BackgroundRunSummary]:
        """Return matching logical tasks in newest-batch-first order."""

        filters = filters or BackgroundRunFilters()
        statement = (
            select(BackgroundTask, BackgroundBatch, Job)
            .join(BackgroundBatch, BackgroundBatch.id == BackgroundTask.batch_id)
            .join(Job, Job.id == BackgroundTask.job_id)
        )
        if filters.operation is not None:
            statement = statement.where(BackgroundTask.operation == filters.operation)
        if filters.status is not None:
            statement = statement.where(BackgroundTask.status == filters.status)
        if filters.batch_id is not None:
            statement = statement.where(BackgroundTask.batch_id == filters.batch_id)
        if filters.job_id is not None:
            statement = statement.where(BackgroundTask.job_id == filters.job_id)
        statement = statement.order_by(
            BackgroundBatch.created_at.desc(),
            BackgroundTask.id.desc(),
        )
        rows = list(self.session.execute(statement).tuples())
        task_ids = [task.id for task, _, _ in rows]
        attempts_by_task: dict[int, list[BackgroundAttemptSummary]] = {
            task_id: [] for task_id in task_ids
        }
        if task_ids:
            attempts = self.session.scalars(
                select(BackgroundTaskAttempt)
                .where(BackgroundTaskAttempt.task_id.in_(task_ids))
                .order_by(
                    BackgroundTaskAttempt.task_id,
                    BackgroundTaskAttempt.attempt_number.desc(),
                )
            )
            for attempt in attempts:
                attempts_by_task[attempt.task_id].append(
                    BackgroundAttemptSummary(
                        attempt_number=attempt.attempt_number,
                        status=attempt.status,
                        pipeline_step=attempt.pipeline_step,
                        started_at=attempt.started_at,
                        completed_at=attempt.completed_at,
                        error_message=attempt.error_message,
                    )
                )

        return [
            BackgroundRunSummary(
                task_id=task.id,
                batch_id=batch.id,
                batch_created_at=batch.created_at,
                job_id=job.id,
                company=job.company,
                job_title=job.job_title,
                operation=task.operation,
                status=task.status,
                retry_count=task.retry_count,
                pipeline_step=task.pipeline_step,
                started_at=task.started_at,
                completed_at=task.completed_at,
                error_message=task.error_message,
                attempts=tuple(attempts_by_task[task.id]),
            )
            for task, batch, job in rows
        ]
