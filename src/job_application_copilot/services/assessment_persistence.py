"""Persist one completed assessment execution as the job's current result."""

from job_application_copilot.domain import AssessmentStatus
from job_application_copilot.repositories import AssessmentRepository, Database, JobRepository
from job_application_copilot.repositories.models import Assessment
from job_application_copilot.repositories.models.common import utc_now
from job_application_copilot.services.assessment_execution import AssessmentExecutionResult


class AssessmentPersistenceService:
    """Atomically keep one validated current assessment answer per job."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def persist(self, result: AssessmentExecutionResult) -> Assessment:
        """Store a terminal result without replacing a prior successful answer on failure."""

        with self.database.session() as session:
            job = JobRepository(session).require(result.job_id)
            assessments = AssessmentRepository(session)
            assessment = assessments.get_for_job(job.id)

            if result.succeeded:
                assert result.output is not None
                if assessment is None:
                    assessment = assessments.add(Assessment(job_id=job.id))
                return assessments.replace_with_success(
                    assessment,
                    result.output,
                    document_a_version=result.context.traceability.document_a_version,
                    prompt_version=result.context.traceability.prompt_version,
                    model_name=result.model_name or result.context.traceability.model_identifier,
                    assessed_at=utc_now(),
                    source_job_updated_at=job.assessment_input_updated_at,
                )

            if assessment is None:
                assessment = assessments.add(Assessment(job_id=job.id))
            if assessment.status is AssessmentStatus.ASSESSED:
                return assessment
            return assessments.mark_failed(assessment, _failure_message(result))


def _failure_message(result: AssessmentExecutionResult) -> str:
    message = (result.error_message or "Assessment did not complete.").strip()
    return message or "Assessment did not complete."
