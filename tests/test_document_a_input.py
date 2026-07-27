"""Tests for complete active Document A file-reference preparation."""

from pathlib import Path

import pytest

from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.services import (
    DocumentAInputService,
    DocumentAInputUnavailableError,
)
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database
    finally:
        database.dispose()


def add_document_a(
    database: Database,
    *,
    version: int,
    active: bool,
    file_id: str | None,
    asset_type: ReferenceAssetType = ReferenceAssetType.DOCUMENT,
) -> ReferenceAsset:
    with database.session() as session:
        asset = ReferenceAsset(
            asset_key="document-a",
            asset_type=asset_type,
            name="Document A",
            version=version,
            file_path=f"document_a/document-a-v{version:04d}.docx",
            file_hash=f"sha256:document-a-v{version}",
            is_active=active,
            processing_status=ReferenceAssetProcessingStatus.READY,
            openai_file_id=file_id,
        )
        session.add(asset)
        session.flush()
        return asset


def test_prepares_complete_active_file_reference_with_version_metadata(
    database: Database,
) -> None:
    active = add_document_a(
        database,
        version=2,
        active=True,
        file_id="file_document_a_v2",
    )

    prepared = DocumentAInputService(database).prepare()

    assert prepared.reference_asset_id == active.id
    assert prepared.version == 2
    assert prepared.file_hash == "sha256:document-a-v2"
    assert prepared.stored_filename == "document-a-v0002.docx"
    assert prepared.openai_file_id == "file_document_a_v2"
    assert prepared.uploaded_at.microsecond == 0
    assert prepared.to_openai_input_file() == {
        "type": "input_file",
        "file_id": "file_document_a_v2",
    }


def test_uses_active_version_instead_of_newer_inactive_candidate(
    database: Database,
) -> None:
    add_document_a(
        database,
        version=1,
        active=True,
        file_id="file_active",
    )
    add_document_a(
        database,
        version=2,
        active=False,
        file_id="file_pending_replacement",
    )

    prepared = DocumentAInputService(database).prepare()

    assert prepared.version == 1
    assert prepared.openai_file_id == "file_active"


def test_rejects_missing_active_document_a(database: Database) -> None:
    with pytest.raises(DocumentAInputUnavailableError, match="No active Document A"):
        DocumentAInputService(database).prepare()


def test_rejects_when_only_inactive_document_a_exists(database: Database) -> None:
    add_document_a(
        database,
        version=1,
        active=False,
        file_id="file_inactive",
    )

    with pytest.raises(DocumentAInputUnavailableError, match="No active Document A"):
        DocumentAInputService(database).prepare()


def test_rejects_active_document_without_openai_file_reference(
    database: Database,
) -> None:
    add_document_a(
        database,
        version=1,
        active=True,
        file_id=None,
    )

    with pytest.raises(
        DocumentAInputUnavailableError,
        match="no OpenAI file reference",
    ):
        DocumentAInputService(database).prepare()


def test_rejects_non_document_using_canonical_key(database: Database) -> None:
    add_document_a(
        database,
        version=1,
        active=True,
        file_id="file_wrong_type",
        asset_type=ReferenceAssetType.TEMPLATE,
    )

    with pytest.raises(
        DocumentAInputUnavailableError,
        match="not the canonical Document A",
    ):
        DocumentAInputService(database).prepare()
