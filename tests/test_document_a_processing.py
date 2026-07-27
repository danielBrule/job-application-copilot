"""Tests for the one-step Document A upload and activation workflow."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from docx import Document

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import ReferenceAssetProcessingStatus
from job_application_copilot.llm import (
    OpenAIClient,
    OpenAIClientError,
    OpenAIConfigurationError,
    UploadedOpenAIFile,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DocumentAProcessingError,
    DocumentAProcessingService,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.remote_reference_operation import (
    release_remote_reference_operation,
    try_acquire_remote_reference_operation,
)


def make_docx(text: str) -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def processing_context(
    tmp_path: Path,
) -> tuple[DocumentAProcessingService, Database, Mock]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    client = Mock(spec=OpenAIClient)
    client.upload_docx.return_value = UploadedOpenAIFile(
        file_id="file_a_1",
        filename="document-a-v0001.docx",
        size_bytes=1_024,
        request_id="req_upload",
    )
    try:
        yield (
            DocumentAProcessingService(
                database,
                settings,
                client_factory=lambda _: cast(OpenAIClient, client),
            ),
            database,
            client,
        )
    finally:
        database.dispose()


def test_stores_uploads_and_activates_first_document_a(
    processing_context: tuple[DocumentAProcessingService, Database, Mock],
) -> None:
    service, database, client = processing_context

    activated = service.replace_and_process(
        filename="document-a.docx",
        content=make_docx("Document A"),
    )

    assert activated.asset_key == "document-a"
    assert activated.version == 1
    assert activated.openai_file_id == "file_a_1"
    assert activated.processing_status is ReferenceAssetProcessingStatus.READY
    assert activated.is_active
    with database.session() as session:
        stored = ReferenceAssetRepository(session).require_version("document-a", 1)
        assert stored.file_path == "document_a/document-a-v0001.docx"
    client.upload_docx.assert_called_once()
    client.close.assert_called_once()


def test_replacement_activates_new_version_and_deactivates_previous(
    processing_context: tuple[DocumentAProcessingService, Database, Mock],
) -> None:
    service, database, client = processing_context
    first = service.replace_and_process(
        filename="document-a.docx",
        content=make_docx("First Document A"),
    )
    client.upload_docx.return_value = UploadedOpenAIFile(
        file_id="file_a_2",
        filename="document-a-v0002.docx",
        size_bytes=2_048,
        request_id="req_upload_2",
    )

    second = service.replace_and_process(
        filename="document-a-replacement.docx",
        content=make_docx("Replacement Document A"),
    )

    assert second.version == 2
    assert second.openai_file_id == "file_a_2"
    assert second.is_active
    with database.session() as session:
        repository = ReferenceAssetRepository(session)
        assert not repository.require_version("document-a", first.version).is_active
        assert repository.require_version("document-a", second.version).is_active
    assert client.upload_docx.call_count == 2
    assert client.close.call_count == 2


def test_upload_failure_preserves_previous_active_version(
    processing_context: tuple[DocumentAProcessingService, Database, Mock],
) -> None:
    service, database, client = processing_context
    previous = service.replace_and_process(
        filename="document-a.docx",
        content=make_docx("Active Document A"),
    )
    client.upload_docx.side_effect = OpenAIClientError(
        "OpenAI could not be reached after the configured retries.",
        operation="upload",
        retryable=True,
    )

    with pytest.raises(DocumentAProcessingError, match="could not be reached"):
        service.replace_and_process(
            filename="document-a-replacement.docx",
            content=make_docx("Replacement Document A"),
        )

    with database.session() as session:
        repository = ReferenceAssetRepository(session)
        active = repository.require_version("document-a", previous.version)
        failed = repository.require_version("document-a", 2)
        assert active.is_active
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert not failed.is_active
    assert client.close.call_count == 2


def test_missing_openai_configuration_returns_safe_workflow_error(
    tmp_path: Path,
) -> None:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)

    def fail_client_creation(_: AppSettings) -> OpenAIClient:
        raise OpenAIConfigurationError("OPENAI_API_KEY is required for OpenAI file operations.")

    try:
        service = DocumentAProcessingService(
            database,
            settings,
            client_factory=fail_client_creation,
        )

        with pytest.raises(DocumentAProcessingError, match="OPENAI_API_KEY"):
            service.replace_and_process(
                filename="document-a.docx",
                content=make_docx("Document A"),
            )
    finally:
        database.dispose()


def test_rejects_a_second_remote_operation(
    processing_context: tuple[DocumentAProcessingService, Database, Mock],
) -> None:
    service, _, client = processing_context
    assert try_acquire_remote_reference_operation()
    try:
        with pytest.raises(DocumentAProcessingError, match="already running"):
            service.replace_and_process(
                filename="document-a.docx",
                content=make_docx("Document A"),
            )
    finally:
        release_remote_reference_operation()

    client.upload_docx.assert_not_called()
