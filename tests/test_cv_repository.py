"""Repository lifecycle tests for the current active CV."""

from datetime import date, datetime
from pathlib import Path

import pytest

from job_application_copilot.domain import CvSource, CvStatus, Language, Location
from job_application_copilot.repositories import (
    CvNotFoundError,
    CvRepository,
    CvTransitionError,
    Database,
    create_database,
)
from job_application_copilot.repositories.models import Cv, Job
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def migrated_database(tmp_path: Path) -> Database:
    path = tmp_path / "copilot.db"
    initialize_database(path)
    database = create_database(path)
    try:
        yield database
    finally:
        database.dispose()


def add_job(database: Database) -> Job:
    with database.session() as session:
        job = Job(
            company="Example Ltd",
            job_title="Architect",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Design reliable platforms.",
            date_added=date(2026, 8, 6),
        )
        session.add(job)
        session.flush()
        return job


def test_transitions_initial_cv_to_review_ready_and_approval(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with migrated_database.session() as session:
        repository = CvRepository(session)
        cv = repository.add(
            Cv(
                job_id=job.id,
                source=CvSource.GENERATED,
                status=CvStatus.SELECTED,
                language=Language.EN,
            )
        )
        repository.transition(cv, CvStatus.PENDING)
        repository.transition(cv, CvStatus.GENERATING)
        cv.file_name = "resume.docx"
        cv.file_path = "C:/private/cvs/resume.docx"
        repository.transition(cv, CvStatus.READY_FOR_REVIEW)
        approved = repository.approve(
            cv,
            approved_at=datetime(2026, 8, 6, 13, 0, 0),
            review_notes=" Reviewed in Word. ",
        )

    assert approved.status is CvStatus.APPROVED
    assert approved.approved_at == datetime(2026, 8, 6, 13, 0, 0)
    assert approved.review_notes == "Reviewed in Word."


def test_rejects_approval_or_failure_without_valid_transition(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with migrated_database.session() as session:
        repository = CvRepository(session)
        cv = repository.add(
            Cv(
                job_id=job.id,
                source=CvSource.UPLOADED,
                status=CvStatus.SELECTED,
                language=Language.EN,
            )
        )

        with pytest.raises(CvTransitionError, match="review-ready"):
            repository.approve(cv, approved_at=datetime(2026, 8, 6), review_notes=None)
        with pytest.raises(CvTransitionError, match="requires an error"):
            repository.transition(cv, CvStatus.FAILED)
        with pytest.raises(CvTransitionError, match="Cannot transition"):
            repository.transition(cv, CvStatus.READY_FOR_REVIEW)


def test_requires_existing_cv_record(migrated_database: Database) -> None:
    with migrated_database.session() as session:
        with pytest.raises(CvNotFoundError, match="Job 99"):
            CvRepository(session).require_for_job(99)
