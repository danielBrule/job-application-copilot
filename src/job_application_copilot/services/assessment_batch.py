"""Queue initial job assessments as one durable background batch."""

from dataclasses import dataclass
from enum import StrEnum

from job_application_copilot.domain import BackgroundOperation, BackgroundTaskStatus
from job_application_copilot.repositories import (
    AssessmentRepository,
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    JobRepository,
)
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask


class AssessmentQueueSkipReason(StrEnum):
    """Why a selected job cannot receive an initial assessment task."""

    EXISTING_ASSESSMENT = "EXISTING_ASSESSMENT"
    ASSESSMENT_ALREADY_QUEUED = "ASSESSMENT_ALREADY_QUEUED"


@dataclass(frozen=True, slots=True)
class AssessmentQueueSkip:
    """One selected job excluded from an assessment launch."""

    job_id: int
    reason: AssessmentQueueSkipReason


@dataclass(frozen=True, slots=True)
class AssessmentBatchQueueResult:
    """Durable outcome of attempting to queue selected initial assessments."""

    batch_id: int | None
    queued_job_ids: tuple[int, ...]
    skipped: tuple[AssessmentQueueSkip, ...]


class AssessmentBatchService:
    """Create exactly one initial-assessment task per currently eligible job."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def queue_selected(self, job_ids: tuple[int, ...]) -> AssessmentBatchQueueResult:
        """Queue selected jobs atomically after rechecking their current eligibility."""

        selected_job_ids = tuple(dict.fromkeys(job_ids))
        if not selected_job_ids:
            return AssessmentBatchQueueResult(None, (), ())

        with self.database.session() as session:
            jobs = JobRepository(session)
            assessments = AssessmentRepository(session)
            tasks = BackgroundTaskRepository(session)
            eligible_job_ids: list[int] = []
            skipped: list[AssessmentQueueSkip] = []

            for job_id in selected_job_ids:
                jobs.require(job_id)
                if assessments.get_for_job(job_id) is not None:
                    skipped.append(
                        AssessmentQueueSkip(job_id, AssessmentQueueSkipReason.EXISTING_ASSESSMENT)
                    )
                elif self._has_active_assessment_task(tasks, job_id):
                    skipped.append(
                        AssessmentQueueSkip(
                            job_id,
                            AssessmentQueueSkipReason.ASSESSMENT_ALREADY_QUEUED,
                        )
                    )
                else:
                    eligible_job_ids.append(job_id)

            if not eligible_job_ids:
                return AssessmentBatchQueueResult(None, (), tuple(skipped))

            batch = BackgroundBatchRepository(session).add(
                BackgroundBatch(
                    operation=BackgroundOperation.ASSESSMENT,
                    payload_metadata={"requested_from": "jobs_dashboard"},
                )
            )
            for job_id in eligible_job_ids:
                tasks.add(
                    BackgroundTask(
                        batch_id=batch.id,
                        job_id=job_id,
                        operation=BackgroundOperation.ASSESSMENT,
                    )
                )
            return AssessmentBatchQueueResult(batch.id, tuple(eligible_job_ids), tuple(skipped))

    @staticmethod
    def _has_active_assessment_task(tasks: BackgroundTaskRepository, job_id: int) -> bool:
        return any(
            task.operation is BackgroundOperation.ASSESSMENT
            and task.status in {BackgroundTaskStatus.PENDING, BackgroundTaskStatus.RUNNING}
            for task in tasks.list(job_id=job_id)
        )
