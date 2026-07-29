"""Persistence and aggregation for token-bearing LLM calls."""

import re

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    BackgroundOperation,
    LlmCallStatus,
    LlmUsageTotals,
)
from job_application_copilot.errors import ApplicationValidationError
from job_application_copilot.repositories.models import (
    BackgroundTask,
    BackgroundTaskAttempt,
    Job,
    LlmCall,
)


class LlmCallAssociationError(ApplicationValidationError):
    """Raised when call ownership conflicts with its job, task, or attempt."""


class LlmCallRepository:
    """Read and write LLM-call telemetry in a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, call: LlmCall) -> LlmCall:
        """Persist a call after validating its optional background-work associations."""

        self._validate_safe_metadata(call)
        self._validate_associations(call)
        self.session.add(call)
        self.session.flush()
        return call

    def list(
        self,
        *,
        job_id: int | None = None,
        task_id: int | None = None,
        operation: BackgroundOperation | None = None,
    ) -> list[LlmCall]:
        """Return matching calls in deterministic invocation order."""

        statement = select(LlmCall)
        if job_id is not None:
            statement = statement.where(LlmCall.job_id == job_id)
        if task_id is not None:
            statement = statement.where(LlmCall.task_id == task_id)
        if operation is not None:
            statement = statement.where(LlmCall.operation == operation)
        statement = statement.order_by(
            LlmCall.started_at.asc(),
            LlmCall.call_sequence.asc(),
            LlmCall.id.asc(),
        )
        return list(self.session.scalars(statement))

    def aggregate(
        self,
        *,
        job_id: int,
        operation: BackgroundOperation | None = None,
    ) -> LlmUsageTotals:
        """Return simple dashboard-ready totals, including reported failed-call usage."""

        statement = select(
            func.count(LlmCall.id),
            func.sum(case((LlmCall.status == LlmCallStatus.SUCCEEDED, 1), else_=0)),
            func.sum(case((LlmCall.status == LlmCallStatus.FAILED, 1), else_=0)),
            func.sum(case((LlmCall.input_tokens.is_not(None), 1), else_=0)),
            func.coalesce(func.sum(LlmCall.input_tokens), 0),
            func.coalesce(func.sum(LlmCall.cached_input_tokens), 0),
            func.coalesce(func.sum(LlmCall.cache_write_tokens), 0),
            func.coalesce(func.sum(LlmCall.output_tokens), 0),
            func.coalesce(func.sum(LlmCall.reasoning_tokens), 0),
            func.coalesce(func.sum(LlmCall.total_tokens), 0),
            func.coalesce(func.sum(LlmCall.duration_seconds), 0.0),
        ).where(LlmCall.job_id == job_id)
        if operation is not None:
            statement = statement.where(LlmCall.operation == operation)
        row = self.session.execute(statement).one()
        return LlmUsageTotals(
            call_count=int(row[0]),
            succeeded_count=int(row[1] or 0),
            failed_count=int(row[2] or 0),
            calls_with_usage=int(row[3] or 0),
            input_tokens=int(row[4]),
            cached_input_tokens=int(row[5]),
            cache_write_tokens=int(row[6]),
            output_tokens=int(row[7]),
            reasoning_tokens=int(row[8]),
            total_tokens=int(row[9]),
            duration_seconds=float(row[10]),
        )

    def _validate_associations(self, call: LlmCall) -> None:
        if self.session.get(Job, call.job_id) is None:
            raise LlmCallAssociationError(f"Job {call.job_id} does not exist.")

        task: BackgroundTask | None = None
        if call.task_id is not None:
            task = self.session.get(BackgroundTask, call.task_id)
            if task is None:
                raise LlmCallAssociationError(f"Background task {call.task_id} does not exist.")
            if task.job_id != call.job_id:
                raise LlmCallAssociationError("The LLM call and background task jobs differ.")
            if task.operation is not call.operation:
                raise LlmCallAssociationError("The LLM call and background task operations differ.")

        if call.task_attempt_id is None:
            return
        if task is None:
            raise LlmCallAssociationError(
                "An LLM call with a task attempt must also identify its background task."
            )
        attempt = self.session.get(BackgroundTaskAttempt, call.task_attempt_id)
        if attempt is None:
            raise LlmCallAssociationError(
                f"Background task attempt {call.task_attempt_id} does not exist."
            )
        if attempt.task_id != task.id:
            raise LlmCallAssociationError(
                "The LLM call attempt does not belong to its background task."
            )

    def _validate_safe_metadata(self, call: LlmCall) -> None:
        if (
            call.cache_identity_hash is not None
            and re.fullmatch(r"[0-9a-f]{64}", call.cache_identity_hash) is None
        ):
            raise LlmCallAssociationError(
                "The cache identity must be a lowercase SHA-256 hexadecimal digest."
            )
        if any(
            not isinstance(value, (str, int, bool)) and value is not None
            for value in call.version_metadata.values()
        ):
            raise LlmCallAssociationError(
                "Version metadata values must be non-sensitive scalar identifiers."
            )
