"""Session-scoped persistence operations for current job assessments."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import AssessmentOutput, AssessmentStatus
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

    def list_for_jobs(self, job_ids: tuple[int, ...]) -> list[Assessment]:
        """Return current assessments for the requested jobs."""

        if not job_ids:
            return []
        return list(self.session.scalars(select(Assessment).where(Assessment.job_id.in_(job_ids))))

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

    def replace_with_success(
        self,
        assessment: Assessment,
        output: AssessmentOutput,
        *,
        document_a_version: int,
        prompt_version: int,
        model_name: str,
        assessed_at: datetime,
        source_job_updated_at: datetime,
    ) -> Assessment:
        """Replace only model-owned current-result fields with one validated output."""

        assessment.status = AssessmentStatus.ASSESSED
        assessment.model_relevance = output.model_relevance
        assessment.role_snapshot = output.role_snapshot
        assessment.real_mandate = output.real_mandate
        assessment.primary_role_family = output.primary_role_family
        assessment.secondary_role_family = output.secondary_role_family
        assessment.seniority_fit = output.seniority_fit
        assessment.technical_bar = output.technical_bar
        assessment.tech_bar_fit = output.tech_bar_fit
        assessment.fit_score = output.fit_score
        assessment.priority_score = output.priority_score
        assessment.decision = output.decision
        assessment.decision_reason = output.decision_reason
        assessment.interview_probability_low = output.interview_probability_low
        assessment.interview_probability_high = output.interview_probability_high
        assessment.interview_probability_confidence = output.interview_probability_confidence
        assessment.strong_fit_signals = list(output.strong_fit_signals)
        assessment.red_flags = list(output.red_flags)
        assessment.sustainability_risks = list(output.sustainability_risks)
        assessment.evidence_gaps = list(output.evidence_gaps)
        assessment.evidence_anchors = [anchor.model_dump() for anchor in output.evidence_anchors]
        assessment.material_mandate_dimensions = [
            dimension.model_dump() for dimension in output.material_mandate_dimensions
        ]
        assessment.evidence_confidence = output.evidence_confidence
        assessment.recommended_document_b_lane = output.recommended_document_b_lane
        assessment.secondary_cv_angle = output.secondary_cv_angle
        assessment.overclaiming_risks = list(output.overclaiming_risks)
        assessment.document_a_version = document_a_version
        assessment.prompt_version = prompt_version
        assessment.model_name = model_name
        assessment.assessed_at = assessed_at
        assessment.source_job_updated_at = source_job_updated_at
        assessment.error_message = None
        self.session.flush()
        return assessment
