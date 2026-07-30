"""Transaction-owning application service for job CRUD operations."""

from datetime import timedelta

from job_application_copilot.domain import CreateJob, JobFilters, UpdateJob
from job_application_copilot.repositories import AssessmentRepository, Database
from job_application_copilot.repositories.job_repository import (
    DuplicateJobUrlError,
    JobRepository,
)
from job_application_copilot.repositories.models import Job
from job_application_copilot.repositories.models.common import utc_now


class JobService:
    """Perform atomic job operations independently of the user interface."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, command: CreateJob) -> Job:
        """Create and return a job in one transaction."""

        with self.database.session() as session:
            repository = JobRepository(session)
            self._ensure_url_available(repository, command.job_url)
            return repository.add(
                Job(
                    company=command.company,
                    job_title=command.job_title,
                    location=command.location,
                    language=command.language,
                    source=command.source,
                    job_url=command.job_url,
                    job_description=command.job_description,
                    date_added=command.date_added,
                    general_notes=command.general_notes,
                    relevance_override=command.relevance_override,
                    user_decision=command.user_decision,
                    application_status=command.application_status,
                    application_date=command.application_date,
                    next_action=command.next_action,
                    next_action_date=command.next_action_date,
                    salary_expectation=command.salary_expectation,
                    closure_reason=command.closure_reason,
                )
            )

    def get(self, job_id: int) -> Job | None:
        """Return a job by identifier, or None when it does not exist."""

        with self.database.session() as session:
            return JobRepository(session).get(job_id)

    def update(self, job_id: int, command: UpdateJob) -> Job:
        """Replace editable job values in one transaction."""

        with self.database.session() as session:
            repository = JobRepository(session)
            job = repository.require(job_id)
            self._ensure_url_available(repository, command.job_url, job_id)
            assessment_inputs_changed = (
                job.company != command.company
                or job.job_title != command.job_title
                or job.location != command.location
                or job.language != command.language
                or job.job_description != command.job_description
            )
            job.company = command.company
            job.job_title = command.job_title
            job.location = command.location
            job.language = command.language
            job.source = command.source
            job.job_url = command.job_url
            job.job_description = command.job_description
            job.date_added = command.date_added
            job.general_notes = command.general_notes
            job.relevance_override = command.relevance_override
            job.user_decision = command.user_decision
            job.application_status = command.application_status
            job.application_date = command.application_date
            job.next_action = command.next_action
            job.next_action_date = command.next_action_date
            job.salary_expectation = command.salary_expectation
            job.closure_reason = command.closure_reason
            if assessment_inputs_changed:
                now = utc_now()
                job.assessment_input_updated_at = max(
                    now,
                    job.assessment_input_updated_at + timedelta(seconds=1),
                )
            session.flush()
            return job

    def list(self, filters: JobFilters | None = None) -> list[Job]:
        """Return jobs matching the supplied basic filters."""

        with self.database.session() as session:
            return JobRepository(session).list(filters)

    def assessment_staleness(self, jobs: tuple[Job, ...]) -> dict[int, bool]:
        """Return derived stale state for the supplied persisted jobs."""

        if not jobs:
            return {}
        with self.database.session() as session:
            assessments = AssessmentRepository(session)
            assessments_by_job_id = {
                assessment.job_id: assessment
                for assessment in assessments.list_for_jobs(tuple(job.id for job in jobs))
            }
            return {
                job.id: (assessment is not None and assessments.is_stale(assessment, job))
                for job in jobs
                for assessment in (assessments_by_job_id.get(job.id),)
            }

    def delete(self, job_id: int) -> None:
        """Permanently delete one job and its linked local history."""

        self.delete_many((job_id,))

    def delete_many(self, job_ids: tuple[int, ...]) -> int:
        """Permanently delete selected jobs and their linked local history atomically."""

        unique_job_ids = tuple(dict.fromkeys(job_ids))
        if not unique_job_ids:
            return 0

        with self.database.session() as session:
            repository = JobRepository(session)
            jobs = tuple(repository.require(job_id) for job_id in unique_job_ids)
            for job in jobs:
                repository.delete_with_history(job)
            return len(jobs)

    @staticmethod
    def _ensure_url_available(
        repository: JobRepository,
        job_url: str | None,
        current_job_id: int | None = None,
    ) -> None:
        if job_url is None:
            return

        existing = repository.get_by_url(job_url)
        if existing is not None and existing.id != current_job_id:
            raise DuplicateJobUrlError(existing.id)
