"""Queue eligible English CV-generation work as durable background batches."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    AssessmentStatus,
    BackgroundOperation,
    BackgroundTaskStatus,
    CvSelectionStatus,
    DocumentBRoutingSetStatus,
    UserDecision,
)
from job_application_copilot.repositories import (
    AssessmentRepository,
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    JobRepository,
)
from job_application_copilot.repositories.document_b_routing_repository import (
    DocumentBRoutingRepository,
)
from job_application_copilot.repositories.models import (
    Assessment,
    BackgroundBatch,
    BackgroundTask,
    Job,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)


class CvGenerationQueueSkipReason(StrEnum):
    """Why a job cannot be queued for CV generation right now."""

    NOT_PURSUED = "NOT_PURSUED"
    NOT_SELECTED = "NOT_SELECTED"
    MISSING_ASSESSMENT = "MISSING_ASSESSMENT"
    ASSESSMENT_NOT_READY = "ASSESSMENT_NOT_READY"
    ASSESSMENT_STALE = "ASSESSMENT_STALE"
    MISSING_CV_LANE = "MISSING_CV_LANE"
    CV_LANE_NOT_CURRENT = "CV_LANE_NOT_CURRENT"
    CV_GENERATION_ALREADY_QUEUED = "CV_GENERATION_ALREADY_QUEUED"


@dataclass(frozen=True, slots=True)
class CvGenerationQueueSkip:
    """One job excluded from a requested CV-generation batch."""

    job_id: int
    reason: CvGenerationQueueSkipReason


@dataclass(frozen=True, slots=True)
class CvGenerationBatchQueueResult:
    """Durable outcome of a requested CV-generation batch."""

    batch_id: int | None
    queued_job_ids: tuple[int, ...]
    skipped: tuple[CvGenerationQueueSkip, ...]


class CvGenerationBatchService:
    """Queue one independent CV-generation task per eligible job."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def queue_selected(self, job_ids: tuple[int, ...]) -> CvGenerationBatchQueueResult:
        """Queue the selected jobs after atomically rechecking their eligibility."""

        selected_job_ids = tuple(dict.fromkeys(job_ids))
        if not selected_job_ids:
            return CvGenerationBatchQueueResult(None, (), ())
        with self.database.session() as session:
            jobs = JobRepository(session)
            requested_jobs = tuple(jobs.require(job_id) for job_id in selected_job_ids)
            return self._queue(session, requested_jobs, requested_from="jobs_dashboard_selected")

    def queue_all_eligible_pursued(self) -> CvGenerationBatchQueueResult:
        """Queue every pursued job that remains eligible at submission time."""

        with self.database.session() as session:
            pursued_jobs = tuple(
                job
                for job in JobRepository(session).list()
                if job.user_decision is UserDecision.PURSUE
            )
            return self._queue(session, pursued_jobs, requested_from="jobs_dashboard_all_pursued")

    def _queue(
        self,
        session: Session,
        requested_jobs: tuple[Job, ...],
        *,
        requested_from: str,
    ) -> CvGenerationBatchQueueResult:
        """Create no-or-one batch after determining each job's durable eligibility."""

        assessments = AssessmentRepository(session)
        tasks = BackgroundTaskRepository(session)
        current_lanes = self._current_lanes(session)
        queued_job_ids: list[int] = []
        skipped: list[CvGenerationQueueSkip] = []
        for job in requested_jobs:
            assessment = assessments.get_for_job(job.id)
            reason = self._ineligibility_reason(
                job,
                assessment,
                assessments,
                tasks,
                current_lanes,
            )
            if reason is None:
                queued_job_ids.append(job.id)
            else:
                skipped.append(CvGenerationQueueSkip(job.id, reason))

        if not queued_job_ids:
            return CvGenerationBatchQueueResult(None, (), tuple(skipped))

        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(
                operation=BackgroundOperation.CV_GENERATION,
                payload_metadata={"requested_from": requested_from},
            )
        )
        for job_id in queued_job_ids:
            tasks.add(
                BackgroundTask(
                    batch_id=batch.id,
                    job_id=job_id,
                    operation=BackgroundOperation.CV_GENERATION,
                )
            )
        return CvGenerationBatchQueueResult(batch.id, tuple(queued_job_ids), tuple(skipped))

    @staticmethod
    def _current_lanes(session: Session) -> frozenset[str]:
        assets = ReferenceAssetRepository(session)
        document_b = assets.get_active(DOCUMENT_B_KEY)
        if document_b is None:
            return frozenset()
        routing_set = DocumentBRoutingRepository(session).get_current(document_b.id)
        if routing_set is None or routing_set.status is not DocumentBRoutingSetStatus.VALIDATED:
            return frozenset()
        return frozenset(
            route.lane_id
            for route in DocumentBRoutingRepository(session).list_routes(routing_set.id)
        )

    @staticmethod
    def _ineligibility_reason(
        job: Job,
        assessment: Assessment | None,
        assessments: AssessmentRepository,
        tasks: BackgroundTaskRepository,
        current_lanes: frozenset[str],
    ) -> CvGenerationQueueSkipReason | None:
        if job.user_decision is not UserDecision.PURSUE:
            return CvGenerationQueueSkipReason.NOT_PURSUED
        if job.cv_selection_status is not CvSelectionStatus.SELECTED:
            return CvGenerationQueueSkipReason.NOT_SELECTED
        if assessment is None:
            return CvGenerationQueueSkipReason.MISSING_ASSESSMENT
        if assessment.status is not AssessmentStatus.ASSESSED:
            return CvGenerationQueueSkipReason.ASSESSMENT_NOT_READY
        if assessments.is_stale(assessment, job):
            return CvGenerationQueueSkipReason.ASSESSMENT_STALE
        lane = assessment.selected_cv_lane
        if lane is None:
            return CvGenerationQueueSkipReason.MISSING_CV_LANE
        if lane not in current_lanes:
            return CvGenerationQueueSkipReason.CV_LANE_NOT_CURRENT
        if any(
            task.operation is BackgroundOperation.CV_GENERATION
            and task.status in {BackgroundTaskStatus.PENDING, BackgroundTaskStatus.RUNNING}
            for task in tasks.list(job_id=job.id)
        ):
            return CvGenerationQueueSkipReason.CV_GENERATION_ALREADY_QUEUED
        return None
