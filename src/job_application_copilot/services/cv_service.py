"""Record rendered or uploaded CV files against their jobs."""

from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import CvSource, CvStatus, Language
from job_application_copilot.errors import ApplicationValidationError
from job_application_copilot.repositories import CvRepository, Database, JobRepository
from job_application_copilot.repositories.models import Cv
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFilePathError,
    resolve_path_within,
)


class CvFileValidationError(ApplicationValidationError):
    """Raised when a CV record does not point to an existing shared-CV file."""


class CvReviewNavigation(NamedTuple):
    """Adjacent jobs in the deterministic ready-for-review CV queue."""

    previous_job_id: int | None
    next_job_id: int | None


class CvService:
    """Own the active-CV record after a successful file-producing workflow."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings

    def record_ready(
        self,
        *,
        job_id: int,
        source: CvSource,
        language: Language,
        file_path: Path,
        selected_cv_lane: str | None = None,
        document_a_version: int | None = None,
        document_b_version: int | None = None,
        template_version: int | None = None,
        generation_prompt_versions: dict[str, int] | None = None,
        french_prompt_versions: dict[str, int] | None = None,
        recorded_at: datetime | None = None,
    ) -> Cv:
        path = self._require_shared_cv_file(file_path)
        timestamp = recorded_at or datetime.now(UTC).replace(tzinfo=None)
        with self.database.session() as session:
            JobRepository(session).require(job_id)
            repository = CvRepository(session)
            cv = repository.get_for_job(job_id)
            if cv is None:
                cv = Cv(
                    job_id=job_id,
                    source=source,
                    status=CvStatus.READY_FOR_REVIEW,
                    language=language,
                )
                session.add(cv)
            cv.source = source
            cv.status = CvStatus.READY_FOR_REVIEW
            cv.language = language
            cv.file_name = path.name
            cv.file_path = str(path)
            cv.selected_cv_lane = _clean_optional_text(selected_cv_lane)
            cv.document_a_version = document_a_version
            cv.document_b_version = document_b_version
            cv.template_version = template_version
            cv.generation_prompt_versions = generation_prompt_versions
            cv.french_prompt_versions = french_prompt_versions
            cv.review_notes = None
            cv.generated_or_uploaded_at = timestamp
            cv.approved_at = None
            cv.error_message = None
            session.flush()
            return cv

    def approve(
        self,
        job_id: int,
        *,
        review_notes: str | None = None,
        approved_at: datetime | None = None,
    ) -> Cv:
        timestamp = approved_at or datetime.now(UTC).replace(tzinfo=None)
        with self.database.session() as session:
            return CvRepository(session).approve(
                CvRepository(session).require_for_job(job_id),
                approved_at=timestamp,
                review_notes=review_notes,
            )

    def get_for_job(self, job_id: int) -> Cv | None:
        with self.database.session() as session:
            return CvRepository(session).get_for_job(job_id)

    def list_for_jobs(self, job_ids: tuple[int, ...]) -> dict[int, Cv]:
        with self.database.session() as session:
            return {cv.job_id: cv for cv in CvRepository(session).list_for_jobs(job_ids)}

    def review_navigation(self, job_id: int) -> CvReviewNavigation:
        with self.database.session() as session:
            job_ids = CvRepository(session).list_default_application_status_review_job_ids()
        try:
            position = job_ids.index(job_id)
        except ValueError:
            return CvReviewNavigation(None, None)
        return CvReviewNavigation(
            previous_job_id=job_ids[position - 1] if position else None,
            next_job_id=job_ids[position + 1] if position + 1 < len(job_ids) else None,
        )

    def first_default_application_status_review_job_id(self) -> int | None:
        """Return one generated CV awaiting review before application tracking begins."""

        with self.database.session() as session:
            job_ids = CvRepository(session).list_default_application_status_review_job_ids()
        return job_ids[0] if job_ids else None

    def next_outstanding_default_application_status_review_job_id(
        self, *, excluding_job_id: int
    ) -> int | None:
        """Return a remaining generated CV awaiting application tracking."""

        with self.database.session() as session:
            job_ids = CvRepository(session).list_default_application_status_review_job_ids()
        return next((job_id for job_id in job_ids if job_id != excluding_job_id), None)

    def _require_shared_cv_file(self, file_path: Path) -> Path:
        try:
            path = resolve_path_within(self.settings.cv_folder, file_path)
        except ImmutableFilePathError as error:
            raise CvFileValidationError(
                "CV file must be inside the configured shared CV folder."
            ) from error
        if not path.is_file():
            raise CvFileValidationError(
                "CV file does not exist in the configured shared CV folder."
            )
        return path


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
