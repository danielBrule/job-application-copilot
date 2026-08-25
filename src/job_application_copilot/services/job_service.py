"""Transaction-owning application service for job CRUD operations."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    AssessmentStatus,
    CreateJob,
    CvSelectionStatus,
    DocumentBRoutingSetStatus,
    JobFilters,
    LaneId,
    UpdateJob,
    UserDecision,
)
from job_application_copilot.domain.job_url import canonicalize_linkedin_job_url
from job_application_copilot.errors import ApplicationOperationError, ApplicationValidationError
from job_application_copilot.repositories import (
    AssessmentRepository,
    Database,
    DocumentBRoutingRepository,
    ReferenceAssetRepository,
)
from job_application_copilot.repositories.job_repository import (
    DuplicateJobUrlError,
    JobRepository,
)
from job_application_copilot.repositories.models import Assessment, Job
from job_application_copilot.repositories.models.common import utc_now


@dataclass(frozen=True, slots=True)
class JobAssessmentDetail:
    """Current job and assessment values required by the Job Details view."""

    job: Job
    assessment: Assessment | None
    is_stale: bool


@dataclass(frozen=True, slots=True)
class JobAssessmentSummary:
    """Current assessment values needed by the dashboard, without detailed assessment text."""

    status: AssessmentStatus | None
    decision: str | None
    fit_score: int | None
    interview_probability_low: int | None
    interview_probability_high: int | None
    selected_cv_lane: LaneId | None


@dataclass(frozen=True, slots=True)
class AssessmentReviewNavigation:
    """Adjacent jobs in the deterministic assessed-undecided review queue."""

    previous_job_id: int | None
    next_job_id: int | None


class CvLaneConfigurationError(ApplicationOperationError):
    """Raised when no active validated CV-lane catalogue is available."""


class InvalidCvLaneSelectionError(ApplicationValidationError):
    """Raised when a selected CV lane is outside the active catalogue."""


class AssessmentReviewNotEligibleError(ApplicationValidationError):
    """Raised when a pursue-and-select decision cannot safely select a CV."""


class JobService:
    """Perform atomic job operations independently of the user interface."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, command: CreateJob) -> Job:
        """Create and return a job in one transaction."""

        job_url = canonicalize_linkedin_job_url(command.job_url)
        with self.database.session() as session:
            repository = JobRepository(session)
            self._ensure_url_available(repository, job_url)
            return repository.add(
                Job(
                    company=command.company,
                    job_title=command.job_title,
                    location=command.location,
                    language=command.language,
                    source=command.source,
                    job_url=job_url,
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

        job_url = canonicalize_linkedin_job_url(command.job_url)
        with self.database.session() as session:
            repository = JobRepository(session)
            job = repository.require(job_id)
            self._ensure_url_available(repository, job_url, job_id)
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
            job.job_url = job_url
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

    def record_application(self, job_id: int, *, status: str, application_date: date) -> Job:
        """Persist a user-recorded application outcome without changing job-fit inputs."""

        normalized_status = status.strip()
        if not normalized_status:
            raise ApplicationValidationError("Application status is required.")
        with self.database.session() as session:
            job = JobRepository(session).require(job_id)
            job.application_status = normalized_status
            job.application_date = application_date
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

    def assessment_summaries(self, jobs: tuple[Job, ...]) -> dict[int, JobAssessmentSummary]:
        """Return current dashboard assessment values for the supplied persisted jobs."""

        if not jobs:
            return {}
        with self.database.session() as session:
            assessments = AssessmentRepository(session)
            assessments_by_job_id = {
                assessment.job_id: assessment
                for assessment in assessments.list_for_jobs(tuple(job.id for job in jobs))
            }
            return {
                job.id: JobAssessmentSummary(
                    status=assessment.status if assessment is not None else None,
                    decision=assessment.decision.value
                    if assessment is not None and assessment.decision is not None
                    else None,
                    fit_score=assessment.fit_score if assessment is not None else None,
                    interview_probability_low=(
                        assessment.interview_probability_low if assessment is not None else None
                    ),
                    interview_probability_high=(
                        assessment.interview_probability_high if assessment is not None else None
                    ),
                    selected_cv_lane=(
                        assessment.selected_cv_lane if assessment is not None else None
                    ),
                )
                for job in jobs
                for assessment in (assessments_by_job_id.get(job.id),)
            }

    def assessment_detail(self, job_id: int) -> JobAssessmentDetail:
        """Return one job with its current assessment and derived stale state."""

        with self.database.session() as session:
            job = JobRepository(session).require(job_id)
            assessment = AssessmentRepository(session).get_for_job(job.id)
            return JobAssessmentDetail(
                job=job,
                assessment=assessment,
                is_stale=assessment is not None and AssessmentRepository.is_stale(assessment, job),
            )

    def update_human_review(
        self,
        job_id: int,
        *,
        user_decision: UserDecision,
        assessment_notes: str | None,
        selected_cv_lane: LaneId | None = None,
    ) -> JobAssessmentDetail:
        """Persist human assessment review without changing model-owned fields."""

        normalized_notes = assessment_notes.strip() if assessment_notes is not None else ""
        with self.database.session() as session:
            job = JobRepository(session).require(job_id)
            assessment_repository = AssessmentRepository(session)
            assessment = assessment_repository.require_for_job(job_id)
            if selected_cv_lane is not None:
                allowed_lanes = self._current_cv_lanes(session)
                if selected_cv_lane not in allowed_lanes:
                    raise InvalidCvLaneSelectionError(
                        f"CV lane '{selected_cv_lane}' is not configured for the active Document B."
                    )
            if user_decision is UserDecision.PURSUE:
                self._validate_pursue_and_select(
                    assessment, job, assessment_repository, selected_cv_lane
                )
            job.user_decision = user_decision
            assessment.assessment_notes = normalized_notes or None
            if selected_cv_lane is not None:
                assessment.selected_cv_lane = selected_cv_lane
            if user_decision is UserDecision.PURSUE:
                job.cv_selection_status = CvSelectionStatus.SELECTED
            else:
                job.cv_selection_status = CvSelectionStatus.NOT_SELECTED
            session.flush()
            return JobAssessmentDetail(
                job=job,
                assessment=assessment,
                is_stale=assessment_repository.is_stale(assessment, job),
            )

    def assessment_review_navigation(self, job_id: int) -> AssessmentReviewNavigation:
        """Return neighbouring assessed, undecided jobs for sequential review."""

        job_ids = self.assessment_review_job_ids()
        try:
            position = job_ids.index(job_id)
        except ValueError:
            return AssessmentReviewNavigation(None, None)
        return AssessmentReviewNavigation(
            previous_job_id=job_ids[position - 1] if position > 0 else None,
            next_job_id=job_ids[position + 1] if position + 1 < len(job_ids) else None,
        )

    def assessment_review_job_ids(self) -> tuple[int, ...]:
        """Return the current assessed-undecided review queue in display order."""

        with self.database.session() as session:
            return tuple(job.id for job in JobRepository(session).list_assessed_undecided())

    def first_assessment_review_job_id(self) -> int | None:
        """Return the first assessed job still awaiting human review, if any."""

        job_ids = self.assessment_review_job_ids()
        return job_ids[0] if job_ids else None

    def next_outstanding_assessment_review_job_id(self, *, excluding_job_id: int) -> int | None:
        """Return a remaining assessed job awaiting review, excluding the current job."""

        with self.database.session() as session:
            queue = JobRepository(session).list_assessed_undecided()
        return next((job.id for job in queue if job.id != excluding_job_id), None)

    def delete(self, job_id: int) -> None:
        """Permanently delete one job and its linked local history."""

        self.delete_many((job_id,))

    def available_cv_lanes(self) -> tuple[LaneId, ...]:
        """Return the exact lane catalogue from the active validated Document B route set."""

        with self.database.session() as session:
            return self._current_cv_lanes(session)

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

    @staticmethod
    def _current_cv_lanes(session: Session) -> tuple[LaneId, ...]:
        """Load the only lane IDs eligible for human CV selection."""

        reference_assets = ReferenceAssetRepository(session)
        document_b = reference_assets.get_active(DOCUMENT_B_KEY)
        if document_b is None:
            raise CvLaneConfigurationError(
                "No active Document B routing configuration is available for CV lane selection."
            )
        routing_sets = DocumentBRoutingRepository(session)
        routing_set = routing_sets.get_current(document_b.id)
        if routing_set is None or routing_set.status is not DocumentBRoutingSetStatus.VALIDATED:
            raise CvLaneConfigurationError(
                "The active Document B version has no current validated routing set."
            )
        lanes = tuple(route.lane_id for route in routing_sets.list_routes(routing_set.id))
        if not lanes:
            raise CvLaneConfigurationError(
                "The active Document B routing set contains no selectable CV lanes."
            )
        return lanes

    @staticmethod
    def _validate_pursue_and_select(
        assessment: Assessment,
        job: Job,
        assessment_repository: AssessmentRepository,
        selected_cv_lane: LaneId | None,
    ) -> None:
        """Reject a decision that would select a CV from an unsafe assessment."""

        if selected_cv_lane is None:
            raise AssessmentReviewNotEligibleError(
                "Select a confirmed CV lane before pursuing this job for CV generation."
            )
        if assessment.status is not AssessmentStatus.ASSESSED:
            raise AssessmentReviewNotEligibleError(
                "Only successfully completed assessments can be selected for CV generation."
            )
        if assessment_repository.is_stale(assessment, job):
            raise AssessmentReviewNotEligibleError(
                "This assessment is stale. Reassess the job before selecting it for CV generation."
            )
