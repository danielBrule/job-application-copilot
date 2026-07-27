"""Integration-style tests for OpenAI file-upload orchestration."""

from io import BytesIO
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from docx import Document

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.llm import (
    OpenAIFileClient,
    OpenAIFileClientError,
    UploadedOpenAIFile,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    OpenAIFileUploadError,
    OpenAIFileUploadNotAllowedError,
    OpenAIFileUploadService,
    ReferenceAssetIntegrityError,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


def make_docx(text: str) -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def upload_context(
    tmp_path: Path,
) -> tuple[
    OpenAIFileUploadService,
    ReferenceAssetStorageService,
    Database,
    AppSettings,
    Mock,
]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    client = Mock(spec=OpenAIFileClient)
    service = OpenAIFileUploadService(
        database,
        settings,
        cast(OpenAIFileClient, client),
    )
    try:
        yield (
            service,
            ReferenceAssetStorageService(database, settings),
            database,
            settings,
            client,
        )
    finally:
        database.dispose()


def uploaded_file(file_id: str = "file_123") -> UploadedOpenAIFile:
    return UploadedOpenAIFile(
        file_id=file_id,
        filename="document.docx",
        size_bytes=100,
        request_id="req_123",
    )


def test_document_a_upload_activates_candidate_after_success(
    upload_context: tuple[
        OpenAIFileUploadService,
        ReferenceAssetStorageService,
        Database,
        AppSettings,
        Mock,
    ],
) -> None:
    service, storage, database, _, client = upload_context
    previous = storage.store(
        filename="previous.docx",
        content=make_docx("previous"),
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )
    with database.session() as session:
        active = ReferenceAssetRepository(session).require_version("document-a", previous.version)
        active.processing_status = ReferenceAssetProcessingStatus.READY
        active.is_active = True

    candidate = storage.replace(
        filename="candidate.docx",
        content=make_docx("candidate"),
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )
    client.upload_docx.return_value = uploaded_file()

    result = service.upload("document-a", candidate.version)

    assert result.openai_file_id == "file_123"
    assert result.processing_status is ReferenceAssetProcessingStatus.READY
    assert result.is_active
    assert result.processing_error is None
    with database.session() as session:
        versions = ReferenceAssetRepository(session).list_versions("document-a")
        assert [
            (version.version, version.processing_status, version.is_active) for version in versions
        ] == [
            (2, ReferenceAssetProcessingStatus.READY, True),
            (1, ReferenceAssetProcessingStatus.READY, False),
        ]


def test_document_b_upload_waits_for_vector_store_processing(
    upload_context: tuple[
        OpenAIFileUploadService,
        ReferenceAssetStorageService,
        Database,
        AppSettings,
        Mock,
    ],
) -> None:
    service, storage, database, _, client = upload_context
    candidate = storage.replace(
        filename="document-b.docx",
        content=make_docx("Document B"),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    )
    client.upload_docx.return_value = uploaded_file("file_b")

    result = service.upload("document-b", candidate.version)

    assert result.openai_file_id == "file_b"
    assert result.processing_status is ReferenceAssetProcessingStatus.PENDING
    assert not result.is_active
    with database.session() as session:
        stored = ReferenceAssetRepository(session).require_version("document-b", candidate.version)
        assert stored.openai_file_id == "file_b"


def test_failed_upload_records_safe_error_and_can_be_retried(
    upload_context: tuple[
        OpenAIFileUploadService,
        ReferenceAssetStorageService,
        Database,
        AppSettings,
        Mock,
    ],
) -> None:
    service, storage, database, _, client = upload_context
    candidate = storage.replace(
        filename="document-a.docx",
        content=make_docx("Document A"),
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )
    client.upload_docx.side_effect = [
        OpenAIFileClientError(
            "OpenAI could not be reached after the configured retries.",
            operation="upload",
            retryable=True,
        ),
        uploaded_file(),
    ]

    with pytest.raises(OpenAIFileUploadError, match="could not be reached"):
        service.upload("document-a", candidate.version)

    with database.session() as session:
        failed = ReferenceAssetRepository(session).require_version("document-a", candidate.version)
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert failed.processing_error == (
            "OpenAI could not be reached after the configured retries."
        )
        assert failed.openai_file_id is None

    retried = service.upload("document-a", candidate.version)

    assert retried.processing_status is ReferenceAssetProcessingStatus.READY
    assert retried.processing_error is None
    assert client.upload_docx.call_count == 2


def test_existing_file_id_makes_upload_idempotent(
    upload_context: tuple[
        OpenAIFileUploadService,
        ReferenceAssetStorageService,
        Database,
        AppSettings,
        Mock,
    ],
) -> None:
    service, storage, _, _, client = upload_context
    candidate = storage.replace(
        filename="document-b.docx",
        content=make_docx("Document B"),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    )
    client.upload_docx.return_value = uploaded_file()

    first = service.upload("document-b", candidate.version)
    second = service.upload("document-b", candidate.version)

    assert first.openai_file_id == second.openai_file_id == "file_123"
    client.upload_docx.assert_called_once()


def test_rejects_non_document_asset(
    upload_context: tuple[
        OpenAIFileUploadService,
        ReferenceAssetStorageService,
        Database,
        AppSettings,
        Mock,
    ],
) -> None:
    service, storage, _, _, client = upload_context
    template = storage.replace(
        filename="template.docx",
        content=make_docx("Template"),
        asset_key="cv-template-en",
        asset_type=ReferenceAssetType.TEMPLATE,
        name="English CV template",
        language_code="en",
    )

    with pytest.raises(OpenAIFileUploadNotAllowedError, match="Document A and Document B"):
        service.upload(template.asset_key, template.version)

    client.upload_docx.assert_not_called()


def test_rejects_changed_local_content_and_records_failure(
    upload_context: tuple[
        OpenAIFileUploadService,
        ReferenceAssetStorageService,
        Database,
        AppSettings,
        Mock,
    ],
) -> None:
    service, storage, database, settings, client = upload_context
    candidate = storage.replace(
        filename="document-a.docx",
        content=make_docx("Original"),
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )
    (settings.reference_folder / candidate.file_path).write_bytes(make_docx("Changed"))

    with pytest.raises(ReferenceAssetIntegrityError, match="recorded hash"):
        service.upload(candidate.asset_key, candidate.version)

    client.upload_docx.assert_not_called()
    with database.session() as session:
        failed = ReferenceAssetRepository(session).require_version(
            candidate.asset_key, candidate.version
        )
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert failed.processing_error is not None


def test_persistence_failure_deletes_new_remote_file(
    upload_context: tuple[
        OpenAIFileUploadService,
        ReferenceAssetStorageService,
        Database,
        AppSettings,
        Mock,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, storage, database, _, client = upload_context
    candidate = storage.replace(
        filename="document-a.docx",
        content=make_docx("Document A"),
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )
    client.upload_docx.return_value = uploaded_file("file_orphan")

    def fail_record_success(
        asset_key: str,
        version: int,
        uploaded: UploadedOpenAIFile,
    ) -> ReferenceAsset:
        del asset_key, version, uploaded
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "_record_success", fail_record_success)

    with pytest.raises(OpenAIFileUploadError, match="could not be saved"):
        service.upload(candidate.asset_key, candidate.version)

    client.delete.assert_called_once_with("file_orphan")
    with database.session() as session:
        failed = ReferenceAssetRepository(session).require_version(
            candidate.asset_key, candidate.version
        )
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert failed.processing_error == "The OpenAI file ID could not be saved locally."
