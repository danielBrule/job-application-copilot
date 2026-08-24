"""Tests for the development reference-asset reset service."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import Language, Location, ReferenceAssetType
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import (
    Job,
    PromptContent,
    PromptDefinition,
    ReferenceAsset,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.immutable_file_storage import sha256_file_hash
from job_application_copilot.services.local_directories import ensure_local_directories
from job_application_copilot.services.reference_asset_reset import (
    ReferenceAssetResetError,
    ReferenceAssetResetService,
)


@dataclass
class FakeRemoteCleaner:
    deleted_vector_store_ids: list[str] = field(default_factory=list)
    deleted_file_ids: list[str] = field(default_factory=list)
    closed: bool = False

    def delete_vector_store(self, vector_store_id: str) -> None:
        self.deleted_vector_store_ids.append(vector_store_id)

    def delete_file(self, file_id: str) -> None:
        self.deleted_file_ids.append(file_id)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def reset_context(tmp_path: Path) -> Iterator[tuple[AppSettings, Database]]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    ensure_local_directories(settings)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        yield settings, database
    finally:
        database.dispose()


def test_reset_removes_assets_files_and_remote_resources_but_preserves_jobs_and_definitions(
    reset_context: tuple[AppSettings, Database],
) -> None:
    settings, database = reset_context
    document_path = settings.document_b_folder / "document-b-v0001.docx"
    document_path.write_bytes(b"document")

    with database.session() as session:
        session.add(
            Job(
                company="Example",
                job_title="Engineer",
                location=Location.UK,
                language=Language.EN,
                source="Company website",
                job_description="Build things",
                date_added=date(2026, 7, 27),
            )
        )
        document = ReferenceAsset(
            asset_key="document-b",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document B",
            version=1,
            file_path="document_b/document-b-v0001.docx",
            file_hash="sha256:document",
            openai_file_id="file-document-b",
            openai_vector_store_id="vs-document-b",
        )
        prompt = ReferenceAsset(
            asset_key="assessment",
            asset_type=ReferenceAssetType.PROMPT,
            name="Assessment prompt",
            version=1,
            file_path=None,
            file_hash=sha256_file_hash(b"prompt"),
        )
        session.add_all([document, prompt])
        session.flush()
        session.add(PromptContent(reference_asset_id=prompt.id, content="prompt"))

    cleaner = FakeRemoteCleaner()
    result = ReferenceAssetResetService(
        database,
        settings,
        remote_cleaner_factory=lambda: cleaner,
    ).reset()

    assert result.reference_asset_count == 2
    assert result.local_file_count == 1
    assert result.openai_file_count == 1
    assert result.vector_store_count == 1
    assert cleaner.deleted_vector_store_ids == ["vs-document-b"]
    assert cleaner.deleted_file_ids == ["file-document-b"]
    assert cleaner.closed
    assert not document_path.exists()

    with database.session() as session:
        assert ReferenceAssetRepository(session).list_all() == []
        assert session.scalar(select(func.count()).select_from(PromptContent)) == 0
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        assert session.scalar(select(func.count()).select_from(PromptDefinition)) == 6


def test_reset_without_assets_is_idempotent_and_does_not_require_openai(
    reset_context: tuple[AppSettings, Database],
) -> None:
    settings, database = reset_context
    service = ReferenceAssetResetService(database, settings)

    first = service.reset()
    second = service.reset()

    assert first.reference_asset_count == 0
    assert first.local_file_count == 0
    assert second == first


def test_reset_rejects_tracked_paths_outside_reference_folder_before_deleting_remote_data(
    reset_context: tuple[AppSettings, Database],
) -> None:
    settings, database = reset_context
    with database.session() as session:
        session.add(
            ReferenceAsset(
                asset_key="document-b",
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document B",
                version=1,
                file_path="../outside.docx",
                file_hash="sha256:document",
                openai_file_id="file-document-b",
            )
        )

    cleaner = FakeRemoteCleaner()
    with pytest.raises(ReferenceAssetResetError, match="outside"):
        ReferenceAssetResetService(
            database,
            settings,
            remote_cleaner_factory=lambda: cleaner,
        ).reset()

    assert cleaner.deleted_file_ids == []
    assert not cleaner.closed
    with database.session() as session:
        assert len(ReferenceAssetRepository(session).list_all()) == 1


def test_reset_requires_remote_cleaner_when_openai_metadata_exists(
    reset_context: tuple[AppSettings, Database],
) -> None:
    settings, database = reset_context
    with database.session() as session:
        session.add(
            ReferenceAsset(
                asset_key="document-b",
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document B",
                version=1,
                file_path="document_b/document-b-v0001.docx",
                file_hash="sha256:document",
                openai_file_id="file-document-b",
            )
        )

    with pytest.raises(ReferenceAssetResetError, match="OpenAI cleanup"):
        ReferenceAssetResetService(database, settings).reset()

    with database.session() as session:
        assert len(ReferenceAssetRepository(session).list_all()) == 1
