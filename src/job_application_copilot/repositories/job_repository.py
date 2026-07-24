"""Session-scoped persistence operations for jobs."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from job_application_copilot.domain import JobFilters
from job_application_copilot.repositories.models import Job


class JobNotFoundError(LookupError):
    """Raised when a required job does not exist."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"Job {job_id} does not exist.")


class DuplicateJobUrlError(ValueError):
    """Raised when a non-null URL already belongs to another job."""

    def __init__(self, existing_job_id: int) -> None:
        self.existing_job_id = existing_job_id
        super().__init__(f"Job URL is already used by job {existing_job_id}.")


class JobRepository:
    """Read and write jobs within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: Job) -> Job:
        """Persist a new job and populate its generated values."""

        self.session.add(job)
        self.session.flush()
        return job

    def get(self, job_id: int) -> Job | None:
        """Return a job by identifier, or None when it does not exist."""

        return self.session.get(Job, job_id)

    def require(self, job_id: int) -> Job:
        """Return an existing job or raise an actionable lookup error."""

        job = self.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def get_by_url(self, job_url: str) -> Job | None:
        """Return the job with an exact non-null URL match, if one exists."""

        return self.session.scalar(select(Job).where(Job.job_url == job_url))

    def list(self, filters: JobFilters | None = None) -> list[Job]:
        """Return matching jobs with deterministic newest-first ordering."""

        statement = select(Job)
        if filters is not None:
            search_text = filters.text.strip() if filters.text else ""
            if search_text:
                statement = statement.where(
                    or_(
                        Job.company.icontains(search_text, autoescape=True),
                        Job.job_title.icontains(search_text, autoescape=True),
                    )
                )
            if filters.location is not None:
                statement = statement.where(Job.location == filters.location)
            if filters.language is not None:
                statement = statement.where(Job.language == filters.language)
            if filters.source is not None:
                statement = statement.where(Job.source == filters.source)
            if filters.user_decision is not None:
                statement = statement.where(Job.user_decision == filters.user_decision)
            if filters.application_status is not None:
                statement = statement.where(Job.application_status == filters.application_status)

        statement = statement.order_by(Job.date_added.desc(), Job.id.desc())
        return list(self.session.scalars(statement))

    def delete(self, job: Job) -> None:
        """Delete an existing job in the current transaction."""

        self.session.delete(job)
        self.session.flush()
