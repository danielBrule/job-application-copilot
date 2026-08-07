"""Service tests for recording and approving current CV files."""

from datetime import date, datetime
from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import CvSource, CvStatus, Language, Location
from job_application_copilot.repositories import CvRepository, Database, create_database
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import CvFileValidationError, CvService
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def service_with_job(tmp_path: Path) -> tuple[CvService, Database, Job, AppSettings]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
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
        yield CvService(database, settings), database, job, settings
    finally:
        database.dispose()


def test_records_existing_file_then_approves_it(
    service_with_job: tuple[CvService, Database, Job, AppSettings],
) -> None:
    service, database, job, settings = service_with_job
    settings.cv_folder.mkdir()
    file_path = settings.cv_folder / "resume.docx"
    file_path.write_bytes(b"content")

    recorded = service.record_ready(
        job_id=job.id,
        source=CvSource.GENERATED,
        language=Language.EN,
        file_path=file_path,
        selected_cv_lane="ARCHITECTURE",
        document_a_version=2,
        document_b_version=3,
        template_version=4,
        generation_prompt_versions={"1": 5, "2": 6, "3": 7},
        recorded_at=datetime(2026, 8, 6, 12, 0, 0),
    )

    assert recorded.status is CvStatus.READY_FOR_REVIEW
    assert recorded.file_path == str(file_path.resolve())
    approved = service.approve(
        job.id,
        review_notes="Checked formatting.",
        approved_at=datetime(2026, 8, 6, 13, 0, 0),
    )

    assert approved.status is CvStatus.APPROVED
    assert approved.approved_at == datetime(2026, 8, 6, 13, 0, 0)
    with database.session() as session:
        stored = CvRepository(session).require_for_job(job.id)
        assert stored.review_notes == "Checked formatting."


def test_replacement_resets_prior_approval_only_after_new_file_exists(
    service_with_job: tuple[CvService, Database, Job, AppSettings],
) -> None:
    service, _, job, settings = service_with_job
    settings.cv_folder.mkdir()
    first = settings.cv_folder / "first.docx"
    second = settings.cv_folder / "second.docx"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    service.record_ready(
        job_id=job.id, source=CvSource.GENERATED, language=Language.EN, file_path=first
    )
    service.approve(job.id, approved_at=datetime(2026, 8, 6, 13, 0, 0))

    replacement = service.record_ready(
        job_id=job.id, source=CvSource.GENERATED, language=Language.EN, file_path=second
    )

    assert replacement.status is CvStatus.READY_FOR_REVIEW
    assert replacement.file_name == "second.docx"
    assert replacement.approved_at is None


@pytest.mark.parametrize("inside", [False, True])
def test_rejects_missing_or_outside_cv_file(
    service_with_job: tuple[CvService, Database, Job, AppSettings], inside: bool
) -> None:
    service, _, job, settings = service_with_job
    target = (settings.cv_folder if inside else settings.data_dir / "outside") / "missing.docx"
    target.parent.mkdir(parents=True)

    with pytest.raises(CvFileValidationError):
        service.record_ready(
            job_id=job.id, source=CvSource.UPLOADED, language=Language.EN, file_path=target
        )
