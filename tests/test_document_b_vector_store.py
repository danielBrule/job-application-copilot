"""Integration-style tests for the Document B vector-store lifecycle."""

import hashlib
from io import BytesIO
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from conftest import install_document_b_routing_config, make_routable_document_b
from docx import Document
from sqlalchemy import event
from sqlalchemy.orm import Session

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.llm import (
    OpenAIClient,
    OpenAIVectorStore,
    OpenAIVectorStoreFile,
    OpenAIVectorStoreFileStatus,
    OpenAIVectorStoreSearchResult,
    UploadedOpenAIFile,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.document_b_retrieval_repository import (
    DocumentBRetrievalRepository,
)
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.models.document_b_retrieval import (
    DocumentBVectorRecord,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DocumentBSectionService,
    DocumentBVectorStoreError,
    DocumentBVectorStoreNotAllowedError,
    DocumentBVectorStoreService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.document_b_progress import DocumentBProcessingProgress


def make_docx(text: str) -> bytes:
    return make_routable_document_b(text)


def make_docx_without_heading(text: str) -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def vector_store_context(
    tmp_path: Path,
) -> tuple[
    DocumentBVectorStoreService,
    ReferenceAssetStorageService,
    Database,
    Mock,
]:
    settings = AppSettings(
        _env_file=None,
        data_dir=tmp_path / "data",
        openai_vector_store_timeout_seconds=30,
    )
    install_document_b_routing_config(settings)
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    client = Mock(spec=OpenAIClient)
    client.create_vector_store.return_value = OpenAIVectorStore(
        vector_store_id="vs_candidate",
        status="in_progress",
        usage_bytes=0,
        request_id="req_create",
    )
    client.wait_for_vector_store_file.return_value = completed_file()
    upload_count = 0

    def upload_section(*, filename: str, content: bytes) -> UploadedOpenAIFile:
        nonlocal upload_count
        upload_count += 1
        return UploadedOpenAIFile(
            file_id=f"file_section_{upload_count}",
            filename=filename,
            size_bytes=len(content),
            request_id="req_upload",
        )

    client.upload_text.side_effect = upload_section
    client.search_vector_store.return_value = (
        OpenAIVectorStoreSearchResult(
            file_id="file_section_1",
            filename="document-b.docx",
            score=0.9,
            text="CV generation positioning guidance.",
            attributes={"document_b_version": "2", "section_id": "example"},
        ),
    )
    try:
        yield (
            DocumentBVectorStoreService(
                database,
                settings,
                cast(OpenAIClient, client),
            ),
            ReferenceAssetStorageService(database, settings),
            database,
            client,
        )
    finally:
        database.dispose()


def completed_file(
    *,
    status: OpenAIVectorStoreFileStatus = OpenAIVectorStoreFileStatus.COMPLETED,
    error_code: str | None = None,
) -> OpenAIVectorStoreFile:
    return OpenAIVectorStoreFile(
        file_id="file_candidate",
        vector_store_id="vs_candidate",
        status=status,
        usage_bytes=8_192,
        error_code=error_code,
        request_id="req_poll",
    )


def stored_candidate(
    storage: ReferenceAssetStorageService,
    database: Database,
    *,
    with_previous: bool = True,
) -> ReferenceAsset:
    if with_previous:
        previous = storage.store(
            filename="previous-document-b.docx",
            content=make_docx("Previous Document B"),
            asset_key="document-b",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document B",
        )
        with database.session() as session:
            active = ReferenceAssetRepository(session).require_version(
                previous.asset_key,
                previous.version,
            )
            active.openai_file_id = "file_previous"
            active.openai_vector_store_id = "vs_previous"
            active.openai_vector_store_usage_bytes = 4_096
            active.processing_status = ReferenceAssetProcessingStatus.READY
            active.is_active = True

    candidate = storage.replace(
        filename="candidate-document-b.docx",
        content=make_docx("Candidate Document B"),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    )
    with database.session() as session:
        stored = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        stored.openai_file_id = "file_candidate"
        session.flush()
        return stored


def test_indexes_validates_and_atomically_activates_candidate(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = vector_store_context
    candidate = stored_candidate(storage, database)

    result = service.process(candidate.asset_key, candidate.version)

    assert result.processing_status is ReferenceAssetProcessingStatus.READY
    assert result.is_active
    assert result.openai_vector_store_id == "vs_candidate"
    assert result.openai_vector_store_usage_bytes > 8_192
    assert result.processing_error is None
    client.create_vector_store.assert_called_once_with(
        name=f"job-application-copilot-document-b-v{candidate.version:04d}",
    )
    assert client.upload_text.call_count > 1
    assert client.attach_vector_store_file.call_count == client.upload_text.call_count
    assert client.wait_for_vector_store_file.call_count == client.upload_text.call_count

    with database.session() as session:
        versions = ReferenceAssetRepository(session).list_versions("document-b")
        assert [
            (
                version.version,
                version.is_active,
                version.openai_vector_store_id,
                version.openai_vector_store_usage_bytes,
            )
            for version in versions
        ] == [
            (2, True, "vs_candidate", result.openai_vector_store_usage_bytes),
            (1, False, "vs_previous", 4_096),
        ]
    sections = DocumentBSectionService(database, service.settings).list_sections(candidate.version)
    assert sections[0].section_id == "cv-generation-workflow-and-rules"
    assert any(
        section.section_id
        == "professional-summary-library-head-of-solutions-architecture-data-ai-architecture"
        for section in sections
    )


def test_completed_lifecycle_is_idempotent(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = vector_store_context
    candidate = stored_candidate(storage, database)

    first = service.process(candidate.asset_key, candidate.version)
    second = service.process(candidate.asset_key, candidate.version)

    assert first.id == second.id
    client.create_vector_store.assert_called_once()
    assert client.wait_for_vector_store_file.call_count > 1
    client.search_vector_store.assert_called_once()


def test_reports_section_level_progress(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, _, _ = vector_store_context
    candidate = stored_candidate(storage, service.database)
    events: list[DocumentBProcessingProgress] = []

    service.process(candidate.asset_key, candidate.version, progress=events.append)

    indexing = [event for event in events if event.stage == "indexing"]
    assert events[0].stage == "preparing"
    assert indexing[0].completed_sections == 0
    assert indexing[-1].completed_sections == indexing[-1].total_sections
    assert events[-1].stage == "activating"


def test_reuses_persisted_store_when_retrying_validation(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = vector_store_context
    candidate = stored_candidate(storage, database, with_previous=False)
    client.search_vector_store.return_value = (
        OpenAIVectorStoreSearchResult(
            file_id="file_section_1",
            filename="section.txt",
            score=0.9,
            text="CV generation positioning guidance.",
            attributes={"document_b_version": str(candidate.version), "section_id": "example"},
        ),
    )
    with database.session() as session:
        failed = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        failed.openai_vector_store_id = "vs_candidate"
        failed.processing_status = ReferenceAssetProcessingStatus.FAILED
        failed.processing_error = "Temporary validation failure."

    result = service.process(candidate.asset_key, candidate.version)

    assert result.is_active
    client.create_vector_store.assert_not_called()
    assert client.wait_for_vector_store_file.call_count > 1


def test_recovers_when_another_process_records_section_during_indexing(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = vector_store_context
    candidate = stored_candidate(storage, database)
    section = next(
        item
        for item in DocumentBSectionService(database, service.settings).extract_and_store(
            candidate.version
        )
        if item.heading_level > 0
    )
    injected = False

    def upload_with_concurrent_winner(*, filename: str, content: bytes) -> UploadedOpenAIFile:
        nonlocal injected
        if not injected:
            injected = True
            with database.session() as session:
                DocumentBRetrievalRepository(session).add_vector_record(
                    DocumentBVectorRecord(
                        reference_asset_id=candidate.id,
                        section_id=section.section_id,
                        content_hash="sha256:" + hashlib.sha256(content).hexdigest(),
                        openai_file_id="file_concurrent_winner",
                        vector_store_id="vs_candidate",
                    )
                )
            return UploadedOpenAIFile(
                file_id="file_concurrent_loser",
                filename=filename,
                size_bytes=len(content),
                request_id="req_upload",
            )
        return UploadedOpenAIFile(
            file_id=f"file_section_{client.upload_text.call_count}",
            filename=filename,
            size_bytes=len(content),
            request_id="req_upload",
        )

    client.upload_text.side_effect = upload_with_concurrent_winner

    result = service.process(candidate.asset_key, candidate.version)

    assert result.is_active
    client.delete_file.assert_called_once_with("file_concurrent_loser")
    with database.session() as session:
        records = (
            session.query(DocumentBVectorRecord).filter_by(reference_asset_id=candidate.id).all()
        )
    assert len(records) == len(
        [
            item
            for item in DocumentBSectionService(database, service.settings).list_sections(
                candidate.version
            )
            if item.heading_level > 0
        ]
    )


def test_processing_without_store_id_resumes_interrupted_creation(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = vector_store_context
    candidate = stored_candidate(storage, database, with_previous=False)
    client.search_vector_store.return_value = (
        OpenAIVectorStoreSearchResult(
            file_id="file_section_1",
            filename="section.txt",
            score=0.9,
            text="CV generation positioning guidance.",
            attributes={"document_b_version": str(candidate.version), "section_id": "example"},
        ),
    )
    with database.session() as session:
        interrupted = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        interrupted.processing_status = ReferenceAssetProcessingStatus.PROCESSING
        interrupted.openai_vector_store_id = None

    result = service.process(candidate.asset_key, candidate.version)

    assert result.processing_status is ReferenceAssetProcessingStatus.READY
    assert result.is_active
    client.create_vector_store.assert_called_once()
    assert client.wait_for_vector_store_file.call_count > 1


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        (OpenAIVectorStoreFileStatus.FAILED, "invalid_file"),
        (OpenAIVectorStoreFileStatus.CANCELLED, None),
    ],
)
def test_terminal_indexing_failure_preserves_previous_active_version(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
    status: OpenAIVectorStoreFileStatus,
    error_code: str | None,
) -> None:
    service, storage, database, client = vector_store_context
    candidate = stored_candidate(storage, database)
    client.wait_for_vector_store_file.return_value = completed_file(
        status=status,
        error_code=error_code,
    )

    with pytest.raises(DocumentBVectorStoreError, match=status.value):
        service.process(candidate.asset_key, candidate.version)

    with database.session() as session:
        previous = ReferenceAssetRepository(session).require_version("document-b", 1)
        failed = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        assert previous.is_active
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert not failed.is_active
        assert failed.openai_vector_store_id == "vs_candidate"
        assert failed.processing_error is not None


def test_empty_validation_search_preserves_previous_active_version(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = vector_store_context
    candidate = stored_candidate(storage, database)
    client.search_vector_store.return_value = (
        OpenAIVectorStoreSearchResult(
            file_id="another_file",
            filename="other.docx",
            score=0.8,
            text="Other content",
        ),
    )

    with pytest.raises(DocumentBVectorStoreError, match="no Document B content"):
        service.process(candidate.asset_key, candidate.version)

    with database.session() as session:
        previous = ReferenceAssetRepository(session).require_version("document-b", 1)
        failed = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        assert previous.is_active
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert failed.openai_vector_store_id == "vs_candidate"


def test_activation_failure_rolls_back_previous_deactivation(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, _ = vector_store_context
    candidate = stored_candidate(storage, database)

    def fail_candidate_activation(
        session: Session,
        flush_context: object,
        instances: object,
    ) -> None:
        del flush_context, instances
        if any(
            isinstance(item, ReferenceAsset)
            and item.version == candidate.version
            and item.is_active
            for item in session.dirty
        ):
            raise RuntimeError("database unavailable")

    session_class = database.session_factory.class_
    event.listen(session_class, "before_flush", fail_candidate_activation)
    try:
        with pytest.raises(DocumentBVectorStoreError, match="could not be activated"):
            service.process(candidate.asset_key, candidate.version)
    finally:
        event.remove(session_class, "before_flush", fail_candidate_activation)

    with database.session() as session:
        previous = ReferenceAssetRepository(session).require_version("document-b", 1)
        failed = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        assert previous.is_active
        assert previous.openai_vector_store_id == "vs_previous"
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert not failed.is_active


def test_store_id_persistence_failure_compensates_new_remote_store(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, storage, database, client = vector_store_context
    candidate = stored_candidate(storage, database, with_previous=False)

    def fail_record(
        asset_key: str,
        version: int,
        created: OpenAIVectorStore,
    ) -> None:
        del asset_key, version, created
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "_record_vector_store_id", fail_record)

    with pytest.raises(DocumentBVectorStoreError, match="could not be saved"):
        service.process(candidate.asset_key, candidate.version)

    client.delete_vector_store.assert_called_once_with("vs_candidate")
    with database.session() as session:
        failed = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert failed.openai_vector_store_id is None


def test_rejects_missing_openai_file_id(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, _, client = vector_store_context
    candidate = storage.replace(
        filename="candidate-document-b.docx",
        content=make_docx("Candidate Document B"),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    )

    with pytest.raises(DocumentBVectorStoreNotAllowedError, match="uploaded to OpenAI"):
        service.process(candidate.asset_key, candidate.version)

    client.create_vector_store.assert_not_called()


def test_rejects_non_canonical_document(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = vector_store_context
    candidate = storage.replace(
        filename="candidate-document-a.docx",
        content=make_docx("Candidate Document A"),
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )
    with database.session() as session:
        stored = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        stored.openai_file_id = "file_a"

    with pytest.raises(DocumentBVectorStoreNotAllowedError, match="canonical Document B"):
        service.process(candidate.asset_key, candidate.version)

    client.create_vector_store.assert_not_called()


def test_extraction_failure_preserves_previous_active_version(
    vector_store_context: tuple[
        DocumentBVectorStoreService,
        ReferenceAssetStorageService,
        Database,
        Mock,
    ],
) -> None:
    service, storage, database, client = vector_store_context
    previous = stored_candidate(storage, database, with_previous=False)
    with database.session() as session:
        active = ReferenceAssetRepository(session).require_version(
            previous.asset_key,
            previous.version,
        )
        active.processing_status = ReferenceAssetProcessingStatus.READY
        active.is_active = True

    candidate = storage.replace(
        filename="candidate-without-headings.docx",
        content=make_docx_without_heading("No usable heading structure."),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    )
    with database.session() as session:
        stored = ReferenceAssetRepository(session).require_version(
            candidate.asset_key,
            candidate.version,
        )
        stored.openai_file_id = "file_without_headings"

    with pytest.raises(DocumentBVectorStoreError, match="no recognised headings"):
        service.process(candidate.asset_key, candidate.version)

    with database.session() as session:
        repository = ReferenceAssetRepository(session)
        assert repository.require_version("document-b", previous.version).is_active
        failed = repository.require_version("document-b", candidate.version)
        assert not failed.is_active
        assert failed.processing_status is ReferenceAssetProcessingStatus.FAILED
        assert "no recognised headings" in (failed.processing_error or "")
    client.create_vector_store.assert_not_called()
