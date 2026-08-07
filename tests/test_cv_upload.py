"""Tests for the user-provided CV upload workflow."""

from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import CvSource, CvStatus, Language, Location
from job_application_copilot.repositories import CvRepository, Database, create_database
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import CvUploadService, CvUploadValidationError
from job_application_copilot.services.database_bootstrap import initialize_database


def make_docx(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def upload_service(tmp_path: Path) -> tuple[CvUploadService, Database, Job, AppSettings]:
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
                date_added=date(2026, 8, 7),
            )
            session.add(job)
            session.flush()
        yield CvUploadService(database, settings), database, job, settings
    finally:
        database.dispose()


def test_uploads_valid_docx_and_records_review_ready_cv(
    upload_service: tuple[CvUploadService, Database, Job, AppSettings],
) -> None:
    service, database, job, settings = upload_service
    content = make_docx("Existing CV")

    cv = service.upload(
        job_id=job.id,
        filename="Daniel Brule CV.docx",
        content=content,
        recorded_at=datetime(2026, 8, 7, 12, 0, 0),
    )

    stored_path = Path(cv.file_path or "")
    assert cv.source is CvSource.UPLOADED
    assert cv.status is CvStatus.READY_FOR_REVIEW
    assert cv.language is Language.EN
    assert cv.file_name == "uploaded - job-1 - Daniel Brule CV.docx"
    assert stored_path.read_bytes() == content
    assert stored_path.parent == settings.cv_folder.resolve()
    with database.session() as session:
        assert CvRepository(session).require_for_job(job.id).generated_or_uploaded_at == datetime(
            2026, 8, 7, 12, 0, 0
        )


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("cv.pdf", make_docx("CV"), ".docx extension"),
        ("cv.docx", b"not a DOCX", "valid DOCX archive"),
    ],
    ids=("wrong-extension", "invalid-content"),
)
def test_rejects_invalid_upload_without_creating_file(
    upload_service: tuple[CvUploadService, Database, Job, AppSettings],
    filename: str,
    content: bytes,
    message: str,
) -> None:
    service, database, job, settings = upload_service

    with pytest.raises(CvUploadValidationError, match=message):
        service.upload(job_id=job.id, filename=filename, content=content)

    assert not settings.cv_folder.exists()
    with database.session() as session:
        assert CvRepository(session).get_for_job(job.id) is None


def test_upload_uses_unique_name_without_overwriting_existing_file(
    upload_service: tuple[CvUploadService, Database, Job, AppSettings],
) -> None:
    service, _, job, settings = upload_service
    settings.cv_folder.mkdir()
    existing = settings.cv_folder / "uploaded - job-1 - Existing.docx"
    existing.write_bytes(b"existing")

    cv = service.upload(job_id=job.id, filename="Existing.docx", content=make_docx("New CV"))

    assert existing.read_bytes() == b"existing"
    assert cv.file_name == "uploaded - job-1 - Existing (2).docx"


def test_upload_removes_new_file_when_cv_persistence_fails(
    upload_service: tuple[CvUploadService, Database, Job, AppSettings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, job, settings = upload_service

    def fail_record_ready(**_: object) -> None:
        raise RuntimeError("database failure")

    monkeypatch.setattr(service.cv_service, "record_ready", fail_record_ready)

    with pytest.raises(RuntimeError, match="database failure"):
        service.upload(job_id=job.id, filename="Existing.docx", content=make_docx("CV"))

    assert not settings.cv_folder.exists() or not tuple(settings.cv_folder.iterdir())
