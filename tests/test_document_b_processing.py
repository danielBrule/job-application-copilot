"""Tests for the complete user-triggered Document B processing workflow."""

from __future__ import annotations

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
    OpenAIClient,
    OpenAIClientError,
    OpenAIConfigurationError,
    OpenAIVectorStore,
    OpenAIVectorStoreFile,
    OpenAIVectorStoreFileStatus,
    OpenAIVectorStoreSearchResult,
    UploadedOpenAIFile,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DocumentBProcessingError,
    DocumentBProcessingService,
    ReferenceAssetStorageService,
    document_b_processing,
)
from job_application_copilot.services.database_bootstrap import initialize_database


def make_docx(text: str) -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def processing_context(
    tmp_path: Path,
) -> tuple[
    DocumentBProcessingService,
    ReferenceAssetStorageService,
    Database,
    Mock,
]:
    settings = AppSettings(
        _env_file=None,
        data_dir=tmp_path / "data",
        openai_vector_store_timeout_seconds=30,
    )
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    client = Mock(spec=OpenAIClient)
    client.upload_docx.return_value = UploadedOpenAIFile(
        file_id="file_candidate",
        filename="document-b-v0001.docx",
        size_bytes=1_024,
        request_id="req_upload",
    )
    client.create_vector_store.return_value = OpenAIVectorStore(
        vector_store_id="vs_candidate",
        status="in_progress",
        usage_bytes=0,
        request_id="req_create",
    )
    client.wait_for_vector_store_file.return_value = OpenAIVectorStoreFile(
        file_id="file_candidate",
        vector_store_id="vs_candidate",
        status=OpenAIVectorStoreFileStatus.COMPLETED,
        usage_bytes=8_192,
        error_code=None,
        request_id="req_poll",
    )
    client.search_vector_store.return_value = (
        OpenAIVectorStoreSearchResult(
            file_id="file_candidate",
            filename="document-b-v0001.docx",
            score=0.9,
            text="CV generation and positioning guidance.",
        ),
    )
    try:
        yield (
            DocumentBProcessingService(
                database,
                settings,
                client_factory=lambda _: cast(OpenAIClient, client),
            ),
            ReferenceAssetStorageService(database, settings),
            database,
            client,
        )
    finally:
        database.dispose()


def store_candidate(
    storage: ReferenceAssetStorageService,
    text: str = "Document B",
) -> int:
    return storage.replace(
        filename="document-b.docx",
        content=make_docx(text),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    ).version


def test_uploads_before_indexing_and_activates_candidate(
    processing_context: tuple[
        DocumentBProcessingService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, _, client = processing_context
    version = store_candidate(storage)

    activated = service.process(version)

    assert activated.processing_status is ReferenceAssetProcessingStatus.READY
    assert activated.is_active
    assert activated.openai_file_id == "file_candidate"
    assert activated.openai_vector_store_id == "vs_candidate"
    assert [call[0] for call in client.method_calls] == [
        "upload_docx",
        "create_vector_store",
        "wait_for_vector_store_file",
        "search_vector_store",
        "close",
    ]


def test_replaces_stores_and_activates_document_b_in_one_workflow(
    processing_context: tuple[
        DocumentBProcessingService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, _, database, client = processing_context

    activated = service.replace_and_process(
        filename="replacement.docx",
        content=make_docx("Replacement Document B"),
    )

    assert activated.asset_key == "document-b"
    assert activated.version == 1
    assert activated.processing_status is ReferenceAssetProcessingStatus.READY
    assert activated.is_active
    with database.session() as session:
        stored = ReferenceAssetRepository(session).require_version("document-b", 1)
        assert stored.file_path == "document_b/document-b-v0001.docx"
    client.upload_docx.assert_called_once()
    client.create_vector_store.assert_called_once()


def test_existing_openai_file_is_not_uploaded_again(
    processing_context: tuple[
        DocumentBProcessingService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = processing_context
    version = store_candidate(storage)
    with database.session() as session:
        candidate = ReferenceAssetRepository(session).require_version("document-b", version)
        candidate.openai_file_id = "file_candidate"

    activated = service.process(version)

    assert activated.is_active
    client.upload_docx.assert_not_called()
    client.create_vector_store.assert_called_once()
    client.close.assert_called_once()


def test_upload_failure_preserves_previous_active_version_and_closes_client(
    processing_context: tuple[
        DocumentBProcessingService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = processing_context
    previous_version = store_candidate(storage)
    with database.session() as session:
        previous = ReferenceAssetRepository(session).require_version(
            "document-b",
            previous_version,
        )
        previous.processing_status = ReferenceAssetProcessingStatus.READY
        previous.is_active = True
    candidate_version = store_candidate(storage, "Replacement Document B")
    client.upload_docx.side_effect = OpenAIClientError(
        "OpenAI could not be reached after the configured retries.",
        operation="upload",
        retryable=True,
    )

    with pytest.raises(DocumentBProcessingError, match="could not be reached"):
        service.process(candidate_version)

    client.create_vector_store.assert_not_called()
    client.close.assert_called_once()
    with database.session() as session:
        previous = ReferenceAssetRepository(session).require_version(
            "document-b",
            previous_version,
        )
        candidate = ReferenceAssetRepository(session).require_version(
            "document-b",
            candidate_version,
        )
        assert previous.is_active
        assert candidate.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert not candidate.is_active


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
        service = DocumentBProcessingService(
            database,
            settings,
            client_factory=fail_client_creation,
        )

        with pytest.raises(DocumentBProcessingError, match="OPENAI_API_KEY"):
            service.process(1)
    finally:
        database.dispose()


def test_rejects_a_second_attempt_while_processing_is_running(
    processing_context: tuple[
        DocumentBProcessingService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, _, _, client = processing_context
    assert document_b_processing._DOCUMENT_B_PROCESSING_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(DocumentBProcessingError, match="already processing"):
            service.process(1)
    finally:
        document_b_processing._DOCUMENT_B_PROCESSING_LOCK.release()

    client.upload_docx.assert_not_called()
