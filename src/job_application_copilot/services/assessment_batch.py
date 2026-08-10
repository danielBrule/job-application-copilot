"""Queue initial job assessments as one durable background batch."""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    AssessmentStatus,
    BackgroundOperation,
    BackgroundTaskStatus,
)
from job_application_copilot.repositories import (
    AssessmentRepository,
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    JobRepository,
)
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask


class AssessmentQueueSkipReason(StrEnum):
    """Why a selected job cannot receive the requested assessment task."""

    EXISTING_ASSESSMENT = "EXISTING_ASSESSMENT"
    NO_ASSESSMENT = "NO_ASSESSMENT"
    ASSESSMENT_NOT_STALE = "ASSESSMENT_NOT_STALE"
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


@dataclass(frozen=True, slots=True)
class AssessmentSelectionEligibility:
    """Assessment actions currently available for a selected set of jobs."""

    initial_assessment_job_ids: tuple[int, ...]
    reassessment_job_ids: tuple[int, ...]


class AssessmentBatchService:
    """Create exactly one initial-assessment task per currently eligible job."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def selection_eligibility(
        self,
        job_ids: tuple[int, ...],
    ) -> AssessmentSelectionEligibility:
        """Return the assessment actions available without changing durable state.

        Queue methods recheck these rules inside their own transaction before
        creating work, because a worker or another UI rerun can change them.
        """

        selected_job_ids = tuple(dict.fromkeys(job_ids))
        if not selected_job_ids:
            return AssessmentSelectionEligibility((), ())

        with self.database.session() as session:
            jobs = JobRepository(session)
            assessments = AssessmentRepository(session)
            tasks = BackgroundTaskRepository(session)
            initial_assessment_job_ids: list[int] = []
            reassessment_job_ids: list[int] = []

            for job_id in selected_job_ids:
                job = jobs.require(job_id)
                assessment = assessments.get_for_job(job_id)
                if self._has_active_assessment_task(tasks, job_id):
                    continue
                if assessment is None:
                    initial_assessment_job_ids.append(job_id)
                elif assessment.status is AssessmentStatus.FAILED or assessments.is_stale(
                    assessment, job
                ):
                    reassessment_job_ids.append(job_id)

            return AssessmentSelectionEligibility(
                tuple(initial_assessment_job_ids),
                tuple(reassessment_job_ids),
            )

    def queue_selected(self, job_ids: tuple[int, ...]) -> AssessmentBatchQueueResult:
        """Queue selected jobs atomically after rechecking their current eligibility."""

        selected_job_ids = tuple(dict.fromkeys(job_ids))
        if not selected_job_ids:
            return AssessmentBatchQueueResult(None, (), ())

        with self.database.session() as session:
            return self._queue_initial_assessments(
                session,
                selected_job_ids,
                requested_from="jobs_dashboard_selected",
            )

    def queue_all_unassessed(self) -> AssessmentBatchQueueResult:
        """Queue every job that does not yet have an assessment."""

        with self.database.session() as session:
            job_ids = tuple(job.id for job in JobRepository(session).list())
            return self._queue_initial_assessments(
                session,
                job_ids,
                requested_from="jobs_dashboard_all_unassessed",
            )

    def _queue_initial_assessments(
        self,
        session: Session,
        job_ids: tuple[int, ...],
        *,
        requested_from: str,
    ) -> AssessmentBatchQueueResult:
        """Queue initial assessments after atomically rechecking durable state."""

        jobs = JobRepository(session)
        assessments = AssessmentRepository(session)
        tasks = BackgroundTaskRepository(session)
        eligible_job_ids: list[int] = []
        skipped: list[AssessmentQueueSkip] = []

        for job_id in job_ids:
            jobs.require(job_id)
            if assessments.get_for_job(job_id) is not None:
                skipped.append(
                    AssessmentQueueSkip(job_id, AssessmentQueueSkipReason.EXISTING_ASSESSMENT)
                )
            elif self._has_active_assessment_task(tasks, job_id):
                skipped.append(
                    AssessmentQueueSkip(job_id, AssessmentQueueSkipReason.ASSESSMENT_ALREADY_QUEUED)
                )
            else:
                eligible_job_ids.append(job_id)

        if not eligible_job_ids:
            return AssessmentBatchQueueResult(None, (), tuple(skipped))

        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(
                operation=BackgroundOperation.ASSESSMENT,
                payload_metadata={"requested_from": requested_from},
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

    def queue_reassessment_selected(self, job_ids: tuple[int, ...]) -> AssessmentBatchQueueResult:
        """Queue failed or stale successful assessments after rechecking eligibility."""

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
                job = jobs.require(job_id)
                assessment = assessments.get_for_job(job_id)
                if assessment is None:
                    skipped.append(
                        AssessmentQueueSkip(job_id, AssessmentQueueSkipReason.NO_ASSESSMENT)
                    )
                elif self._has_active_assessment_task(tasks, job_id):
                    skipped.append(
                        AssessmentQueueSkip(
                            job_id,
                            AssessmentQueueSkipReason.ASSESSMENT_ALREADY_QUEUED,
                        )
                    )
                elif assessment.status is AssessmentStatus.FAILED or assessments.is_stale(
                    assessment, job
                ):
                    eligible_job_ids.append(job_id)
                else:
                    skipped.append(
                        AssessmentQueueSkip(
                            job_id,
                            AssessmentQueueSkipReason.ASSESSMENT_NOT_STALE,
                        )
                    )

            if not eligible_job_ids:
                return AssessmentBatchQueueResult(None, (), tuple(skipped))

            batch = BackgroundBatchRepository(session).add(
                BackgroundBatch(
                    operation=BackgroundOperation.ASSESSMENT,
                    payload_metadata={
                        "requested_from": "jobs_dashboard",
                        "assessment_mode": "reassessment",
                    },
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
