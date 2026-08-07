"""Constraint tests for one job's active CV record."""

from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from job_application_copilot.domain import CvSource, CvStatus, Language, Location
from job_application_copilot.repositories import Database, create_database
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


def ready_cv(job: Job, **overrides: object) -> Cv:
    values: dict[str, object] = {
        "job_id": job.id,
        "source": CvSource.GENERATED,
        "status": CvStatus.READY_FOR_REVIEW,
        "language": Language.EN,
        "file_name": "resume.docx",
        "file_path": "C:/private/cvs/resume.docx",
        "selected_cv_lane": "ARCHITECTURE",
        "document_a_version": 2,
        "document_b_version": 3,
        "template_version": 1,
        "generation_prompt_versions": {"1": 2, "2": 3, "3": 4},
        "generated_or_uploaded_at": datetime(2026, 8, 6, 12, 0, 0),
    }
    values.update(overrides)
    return Cv(**values)


def test_persists_ready_generated_cv_with_traceability(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with migrated_database.session() as session:
        cv = ready_cv(job)
        session.add(cv)
        session.flush()
        cv_id = cv.id

    with migrated_database.session() as session:
        stored = session.get(Cv, cv_id)

    assert stored is not None
    assert stored.status is CvStatus.READY_FOR_REVIEW
    assert stored.source is CvSource.GENERATED
    assert stored.generation_prompt_versions == {"1": 2, "2": 3, "3": 4}
    assert stored.approved_at is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"file_name": None}, "ready_requires_file"),
        ({"status": CvStatus.APPROVED}, "approval_matches_status"),
        ({"status": CvStatus.FAILED, "error_message": None}, "error_matches_status"),
        ({"status": CvStatus.READY_FOR_REVIEW, "error_message": "failure"}, "error_matches_status"),
    ],
)
def test_rejects_invalid_cv_status_metadata(
    migrated_database: Database, overrides: dict[str, object], constraint: str
) -> None:
    job = add_job(migrated_database)
    with pytest.raises(IntegrityError, match=constraint):
        with migrated_database.session() as session:
            session.add(ready_cv(job, **overrides))
            session.flush()


def test_allows_only_one_current_cv_per_job(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with pytest.raises(IntegrityError, match="cvs.job_id"):
        with migrated_database.session() as session:
            session.add_all([ready_cv(job), ready_cv(job, file_name="replacement.docx")])
            session.flush()
