"""Persistence operations for one job's active CV record."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import CvStatus, is_valid_cv_transition
from job_application_copilot.errors import ApplicationNotFoundError, ApplicationValidationError
from job_application_copilot.repositories.models import Cv


class CvNotFoundError(ApplicationNotFoundError):
    """Raised when a job has no active CV record."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"Job {job_id} has no active CV.")


class CvTransitionError(ApplicationValidationError):
    """Raised when an active-CV lifecycle transition is not permitted."""


class CvRepository:
    """Read and write the single current CV record for each job."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_job(self, job_id: int) -> Cv | None:
        return self.session.scalar(select(Cv).where(Cv.job_id == job_id))

    def require_for_job(self, job_id: int) -> Cv:
        cv = self.get_for_job(job_id)
        if cv is None:
            raise CvNotFoundError(job_id)
        return cv

    def add(self, cv: Cv) -> Cv:
        self.session.add(cv)
        self.session.flush()
        return cv

    def transition(self, cv: Cv, target: CvStatus, *, error_message: str | None = None) -> Cv:
        if not is_valid_cv_transition(cv.status, target):
            raise CvTransitionError(
                f"Cannot transition CV from {cv.status.value} to {target.value}."
            )
        if target is CvStatus.FAILED:
            message = (error_message or "").strip()
            if not message:
                raise CvTransitionError("A failed CV requires an error message.")
            cv.error_message = message
        else:
            cv.error_message = None
        cv.status = target
        self.session.flush()
        return cv

    def approve(self, cv: Cv, *, approved_at: datetime, review_notes: str | None) -> Cv:
        if cv.status is not CvStatus.READY_FOR_REVIEW:
            raise CvTransitionError("Only a review-ready CV can be approved.")
        cv.status = CvStatus.APPROVED
        cv.approved_at = approved_at
        cv.review_notes = _clean_optional_text(review_notes)
        cv.error_message = None
        self.session.flush()
        return cv


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
