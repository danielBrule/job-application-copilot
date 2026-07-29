"""Session-scoped persistence operations for current job assessments."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import AssessmentStatus
from job_application_copilot.errors import (
    ApplicationNotFoundError,
    ApplicationValidationError,
)
from job_application_copilot.repositories.models import Assessment, Job


class AssessmentNotFoundError(ApplicationNotFoundError):
    """Raised when a job has no current assessment."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"Job {job_id} has no assessment.")


class AssessmentNotAllowedError(ApplicationValidationError):
    """Raised when an assessment lifecycle operation is not permitted."""


class AssessmentRepository:
    """Read and write one current assessment per job."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, assessment: Assessment) -> Assessment:
        """Persist an initial current assessment."""

        self.session.add(assessment)
        self.session.flush()
        return assessment

    def get_for_job(self, job_id: int) -> Assessment | None:
        """Return the current assessment for a job, if present."""

        return self.session.scalar(select(Assessment).where(Assessment.job_id == job_id))

    def require_for_job(self, job_id: int) -> Assessment:
        """Return a current assessment or raise an actionable lookup error."""

        assessment = self.get_for_job(job_id)
        if assessment is None:
            raise AssessmentNotFoundError(job_id)
        return assessment

    @staticmethod
    def is_stale(assessment: Assessment, job: Job) -> bool:
        """Return whether relevant job inputs changed after the stored result."""

        return (
            assessment.status is AssessmentStatus.ASSESSED
            and assessment.source_job_updated_at != job.assessment_input_updated_at
        )

    def mark_running(self, assessment: Assessment) -> Assessment:
        """Start or retry an assessment that has not already succeeded."""

        if assessment.status is AssessmentStatus.ASSESSED:
            raise AssessmentNotAllowedError(
                "A successful assessment remains available while stale reassessment runs."
            )
        if assessment.status is AssessmentStatus.RUNNING:
            raise AssessmentNotAllowedError("Assessment is already running.")
        assessment.status = AssessmentStatus.RUNNING
        assessment.error_message = None
        self.session.flush()
        return assessment

    def mark_failed(self, assessment: Assessment, error_message: str) -> Assessment:
        """Persist failure for an initial or retried unsuccessful assessment."""

        if assessment.status is AssessmentStatus.ASSESSED:
            raise AssessmentNotAllowedError(
                "A failed reassessment must not replace the successful assessment."
            )
        message = error_message.strip()
        if not message:
            raise AssessmentNotAllowedError("A failed assessment requires an error message.")
        assessment.status = AssessmentStatus.FAILED
        assessment.error_message = message
        self.session.flush()
        return assessment
