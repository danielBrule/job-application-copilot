"""Integration tests for immutable local reference-asset storage."""

from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import func, select

from job_application_copilot.config import AppSettings
from job_application_copilot.documents import DocxValidationError
from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DuplicateReferenceAssetError,
    ReferenceAssetStorageError,
    ReferenceAssetStorageService,
    UnsupportedReferenceAssetError,
)
from job_application_copilot.services.database_bootstrap import initialize_database


def make_docx(text: str = "Reference content") -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def storage_service(
    tmp_path: Path,
) -> tuple[ReferenceAssetStorageService, Database, AppSettings]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        yield ReferenceAssetStorageService(database, settings), database, settings
    finally:
        database.dispose()


@pytest.mark.parametrize(
    ("asset_key", "asset_type", "expected_folder"),
    [
        ("document-a", ReferenceAssetType.DOCUMENT, "document_a"),
        ("document-b", ReferenceAssetType.DOCUMENT, "document_b"),
        ("cv-template-en", ReferenceAssetType.TEMPLATE, "templates"),
        (
            "french-example-platform",
            ReferenceAssetType.REFERENCE_EXAMPLE,
            "examples",
        ),
    ],
)
def test_stores_valid_docx_in_configured_category_folder(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
    asset_key: str,
    asset_type: ReferenceAssetType,
    expected_folder: str,
) -> None:
    service, database, settings = storage_service
    content = make_docx(asset_key)

    asset = service.store(
        filename="upload.docx",
        content=content,
        asset_key=asset_key,
        asset_type=asset_type,
        name="Reference asset",
        language_code=" FR ",
    )

    expected_path = settings.reference_folder / expected_folder / f"{asset_key}-v0001.docx"
    assert asset.version == 1
    assert asset.file_path == f"{expected_folder}/{asset_key}-v0001.docx"
    assert asset.file_hash.startswith("sha256:")
    assert len(asset.file_hash) == len("sha256:") + 64
    assert asset.language_code == "fr"
    assert not asset.is_active
    assert asset.processing_status is ReferenceAssetProcessingStatus.PENDING
    assert expected_path.read_bytes() == content

    with database.session() as session:
        stored = session.get(ReferenceAsset, asset.id)
        assert stored is not None
        assert stored.file_path == asset.file_path


def test_assigns_next_version_without_overwriting_previous_file(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
) -> None:
    service, _, settings = storage_service
    first_content = make_docx("version one")
    second_content = make_docx("version two")

    first = service.store(
        filename="first.docx",
        content=first_content,
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )
    second = service.store(
        filename="second.docx",
        content=second_content,
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )

    assert (first.version, second.version) == (1, 2)
    assert (settings.reference_folder / first.file_path).read_bytes() == first_content
    assert (settings.reference_folder / second.file_path).read_bytes() == second_content


def test_rejects_duplicate_content_for_same_asset_key(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
) -> None:
    service, database, settings = storage_service
    content = make_docx()
    service.store(
        filename="first.docx",
        content=content,
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )

    with pytest.raises(DuplicateReferenceAssetError) as error:
        service.store(
            filename="renamed.docx",
            content=content,
            asset_key="document-a",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document A",
        )

    assert error.value.existing_version == 1
    assert list(settings.document_a_folder.glob("*.docx")) == [
        settings.document_a_folder / "document-a-v0001.docx"
    ]
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceAsset)) == 1


def test_allows_same_content_for_different_asset_keys(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
) -> None:
    service, _, _ = storage_service
    content = make_docx()

    document_a = service.store(
        filename="a.docx",
        content=content,
        asset_key="document-a",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document A",
    )
    document_b = service.store(
        filename="b.docx",
        content=content,
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    )

    assert document_a.file_hash == document_b.file_hash


def test_invalid_docx_leaves_no_file_or_metadata(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
) -> None:
    service, database, settings = storage_service

    with pytest.raises(DocxValidationError):
        service.store(
            filename="invalid.docx",
            content=b"not a docx",
            asset_key="document-a",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document A",
        )

    assert not settings.document_a_folder.exists()
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceAsset)) == 0


def test_existing_versioned_file_is_not_deleted_or_overwritten(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
) -> None:
    service, database, settings = storage_service
    settings.document_a_folder.mkdir(parents=True)
    existing_path = settings.document_a_folder / "document-a-v0001.docx"
    existing_path.write_bytes(b"private existing content")

    with pytest.raises(ReferenceAssetStorageError, match="will not be overwritten"):
        service.store(
            filename="new.docx",
            content=make_docx(),
            asset_key="document-a",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document A",
        )

    assert existing_path.read_bytes() == b"private existing content"
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceAsset)) == 0


def test_removes_new_file_when_metadata_write_fails(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, database, settings = storage_service

    def fail_add(
        repository: ReferenceAssetRepository,
        asset: ReferenceAsset,
    ) -> ReferenceAsset:
        del repository, asset
        raise RuntimeError("database write failed")

    monkeypatch.setattr(ReferenceAssetRepository, "add", fail_add)

    with pytest.raises(RuntimeError, match="database write failed"):
        service.store(
            filename="new.docx",
            content=make_docx(),
            asset_key="document-a",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document A",
        )

    assert not (settings.document_a_folder / "document-a-v0001.docx").exists()
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceAsset)) == 0


@pytest.mark.parametrize("asset_key", ["Document-A", "../document-a", "document_a", "a--b"])
def test_rejects_unsafe_asset_key(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
    asset_key: str,
) -> None:
    service, _, _ = storage_service

    with pytest.raises(ValueError, match="lowercase slug"):
        service.store(
            filename="document.docx",
            content=make_docx(),
            asset_key=asset_key,
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document A",
        )


def test_rejects_prompt_and_unknown_document_key(
    storage_service: tuple[ReferenceAssetStorageService, Database, AppSettings],
) -> None:
    service, _, _ = storage_service

    with pytest.raises(UnsupportedReferenceAssetError, match="not stored as DOCX"):
        service.store(
            filename="prompt.docx",
            content=make_docx(),
            asset_key="assessment-prompt",
            asset_type=ReferenceAssetType.PROMPT,
            name="Assessment prompt",
        )

    with pytest.raises(UnsupportedReferenceAssetError, match="document-a.*document-b"):
        service.store(
            filename="document.docx",
            content=make_docx(),
            asset_key="document-c",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document C",
        )
