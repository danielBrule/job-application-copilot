"""Selection of assessed pursued jobs for later CV generation."""

from dataclasses import dataclass
from enum import StrEnum

from job_application_copilot.domain import AssessmentStatus, CvSelectionStatus, UserDecision
from job_application_copilot.repositories import AssessmentRepository, Database, JobRepository
from job_application_copilot.repositories.models import Assessment, Job


class CvSelectionSkipReason(StrEnum):
    """Why a selected job cannot become ready for CV generation."""

    NOT_PURSUED = "NOT_PURSUED"
    MISSING_ASSESSMENT = "MISSING_ASSESSMENT"
    ASSESSMENT_NOT_READY = "ASSESSMENT_NOT_READY"
    ASSESSMENT_STALE = "ASSESSMENT_STALE"
    MISSING_CV_LANE = "MISSING_CV_LANE"
    ALREADY_SELECTED = "ALREADY_SELECTED"


@dataclass(frozen=True, slots=True)
class CvSelectionSkip:
    """One selected job excluded from CV selection."""

    job_id: int
    reason: CvSelectionSkipReason


@dataclass(frozen=True, slots=True)
class CvSelectionResult:
    """Durable outcome of selecting jobs for later CV generation."""

    selected_job_ids: tuple[int, ...]
    skipped: tuple[CvSelectionSkip, ...]


class CvSelectionService:
    """Mark only currently eligible pursued jobs as selected for CV generation."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def select_jobs(self, job_ids: tuple[int, ...]) -> CvSelectionResult:
        """Atomically select every eligible unique job after rechecking its state."""

        selected_job_ids = tuple(dict.fromkeys(job_ids))
        if not selected_job_ids:
            return CvSelectionResult((), ())

        with self.database.session() as session:
            jobs = JobRepository(session)
            assessments = AssessmentRepository(session)
            selected: list[int] = []
            skipped: list[CvSelectionSkip] = []

            for job_id in selected_job_ids:
                job = jobs.require(job_id)
                assessment = assessments.get_for_job(job_id)
                reason = self._ineligibility_reason(job, assessment, assessments)
                if reason is not None:
                    skipped.append(CvSelectionSkip(job_id, reason))
                    continue
                job.cv_selection_status = CvSelectionStatus.SELECTED
                selected.append(job_id)

            session.flush()
            return CvSelectionResult(tuple(selected), tuple(skipped))

    @staticmethod
    def _ineligibility_reason(
        job: Job,
        assessment: Assessment | None,
        assessments: AssessmentRepository,
    ) -> CvSelectionSkipReason | None:
        if job.cv_selection_status is CvSelectionStatus.SELECTED:
            return CvSelectionSkipReason.ALREADY_SELECTED
        if job.user_decision is not UserDecision.PURSUE:
            return CvSelectionSkipReason.NOT_PURSUED
        if assessment is None:
            return CvSelectionSkipReason.MISSING_ASSESSMENT
        if assessment.status is not AssessmentStatus.ASSESSED:
            return CvSelectionSkipReason.ASSESSMENT_NOT_READY
        if assessments.is_stale(assessment, job):
            return CvSelectionSkipReason.ASSESSMENT_STALE
        if assessment.selected_cv_lane is None:
            return CvSelectionSkipReason.MISSING_CV_LANE
        return None
