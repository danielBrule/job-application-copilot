"""Tests for importing file-backed prompt history into SQLite."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import (
    DocumentBSection,
    PromptContent,
    ReferenceAsset,
)
from job_application_copilot.services import (
    PromptContentMigrationError,
    PromptContentMigrationService,
    PromptService,
)
from job_application_copilot.services.database_bootstrap import (
    MIGRATIONS_DIRECTORY,
    initialize_database,
)
from job_application_copilot.services.immutable_file_storage import sha256_file_hash
from job_application_copilot.services.reference_asset_reset import (
    ReferenceAssetResetService,
)

LEGACY_PROMPT_REVISION = "0023_add_material_mandate_dimensions"


def legacy_settings(tmp_path: Path) -> AppSettings:
    """Build a private installation whose database starts before prompt-content storage."""

    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    _upgrade_to_legacy_schema(settings.database_path)
    return settings


def _upgrade_to_legacy_schema(database_path: Path) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
    database = create_database(database_path)
    try:
        with database.engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, LEGACY_PROMPT_REVISION)
            connection.commit()
    finally:
        database.dispose()


def _legacy_prompt(
    *,
    asset_key: str,
    version: int,
    text: str,
    is_active: bool,
    file_path: str | None = None,
) -> ReferenceAsset:
    path = file_path or f"prompts/assessment/{asset_key}-v{version:04d}.txt"
    return ReferenceAsset(
        asset_key=asset_key,
        asset_type=ReferenceAssetType.PROMPT,
        name="Assessment prompt",
        version=version,
        file_path=path,
        file_hash=sha256_file_hash(text.encode("utf-8")),
        is_active=is_active,
        processing_status=ReferenceAssetProcessingStatus.READY,
    )


def _write_legacy_prompt(settings: AppSettings, asset: ReferenceAsset, text: str) -> Path:
    assert asset.file_path is not None
    path = settings.reference_folder / asset.file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _upgrade_and_open(settings: AppSettings) -> Database:
    initialize_database(settings.database_path)
    return create_database(settings.database_path)


def _upgrade_to_head_directly(database_path: Path) -> bool:
    """Exercise Alembic's direct, non-bootstrap SQLite upgrade path."""

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
    database = create_database(database_path)
    try:
        with database.engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            foreign_keys_enabled = (
                int(connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()) == 1
            )
            connection.commit()
            return foreign_keys_enabled
    finally:
        database.dispose()


def test_imports_all_historical_prompt_versions_and_removes_only_tracked_files(
    tmp_path: Path,
) -> None:
    settings = legacy_settings(tmp_path)
    first_text = "Version one."
    second_text = "Version two."
    first = _legacy_prompt(
        asset_key="assessment",
        version=1,
        text=first_text,
        is_active=False,
    )
    second = _legacy_prompt(
        asset_key="assessment",
        version=2,
        text=second_text,
        is_active=True,
    )
    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            session.add_all([first, second])
            session.flush()
            first_id = first.id
            second_id = second.id
        first_path = _write_legacy_prompt(settings, first, first_text)
        second_path = _write_legacy_prompt(settings, second, second_text)
        untracked_path = settings.legacy_prompts_folder / "assessment" / "do-not-delete.txt"
        untracked_path.write_text("Untracked text.", encoding="utf-8")
    finally:
        database.dispose()

    database = _upgrade_and_open(settings)
    try:
        service = PromptContentMigrationService(database, settings)

        result = service.migrate()
        repeated = service.migrate()

        assert result.imported_version_count == 2
        assert result.removed_legacy_file_count == 2
        assert repeated.imported_version_count == 0
        assert repeated.removed_legacy_file_count == 0
        assert not first_path.exists()
        assert not second_path.exists()
        assert untracked_path.read_text(encoding="utf-8") == "Untracked text."
        with database.session() as session:
            stored_first = session.get(ReferenceAsset, first_id)
            stored_second = session.get(ReferenceAsset, second_id)
            assert stored_first is not None
            assert stored_second is not None
            assert stored_first.file_path is None
            assert stored_second.file_path is None
            assert not stored_first.is_active
            assert stored_second.is_active
            assert session.get(PromptContent, first_id).content == first_text
            assert session.get(PromptContent, second_id).content == second_text
    finally:
        database.dispose()


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (None, "cannot be read safely"),
        ("Changed after storage.", "no longer matches"),
    ],
)
def test_rejects_missing_or_tampered_legacy_prompt_without_partial_import(
    tmp_path: Path,
    source: str | None,
    message: str,
) -> None:
    settings = legacy_settings(tmp_path)
    valid = _legacy_prompt(
        asset_key="assessment",
        version=1,
        text="Valid historical content.",
        is_active=False,
    )
    invalid = _legacy_prompt(
        asset_key="assessment",
        version=2,
        text="Expected historical content.",
        is_active=True,
    )
    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            session.add_all([valid, invalid])
        valid_path = _write_legacy_prompt(settings, valid, "Valid historical content.")
        invalid_path = settings.reference_folder / (invalid.file_path or "")
        if source is not None:
            invalid_path.parent.mkdir(parents=True, exist_ok=True)
            invalid_path.write_text(source, encoding="utf-8")
    finally:
        database.dispose()

    database = _upgrade_and_open(settings)
    try:
        with pytest.raises(PromptContentMigrationError, match=message):
            PromptContentMigrationService(database, settings).migrate()

        assert valid_path.exists()
        assert not invalid_path.exists() if source is None else invalid_path.exists()
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(PromptContent)) == 0
    finally:
        database.dispose()


def test_rejects_an_unsafe_legacy_path_without_touching_the_outside_file(tmp_path: Path) -> None:
    settings = legacy_settings(tmp_path)
    outside = tmp_path / "outside-prompt.txt"
    outside.write_text("Historical prompt.", encoding="utf-8")
    asset = _legacy_prompt(
        asset_key="assessment",
        version=1,
        text="Historical prompt.",
        is_active=True,
        file_path="../outside-prompt.txt",
    )
    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            session.add(asset)
    finally:
        database.dispose()

    database = _upgrade_and_open(settings)
    try:
        with pytest.raises(PromptContentMigrationError, match="unsafe legacy path"):
            PromptContentMigrationService(database, settings).migrate()

        assert outside.read_text(encoding="utf-8") == "Historical prompt."
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(PromptContent)) == 0
    finally:
        database.dispose()


def test_direct_schema_upgrade_preserves_document_b_children_during_reference_asset_rebuild(
    tmp_path: Path,
) -> None:
    settings = legacy_settings(tmp_path)
    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            document_b = ReferenceAsset(
                asset_key="document-b",
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document B",
                version=1,
                file_path="document_b/document-b-v0001.docx",
                file_hash="sha256:document-b",
                is_active=True,
                processing_status=ReferenceAssetProcessingStatus.READY,
            )
            session.add(document_b)
            session.flush()
            document_b_id = document_b.id
            section = DocumentBSection(
                reference_asset_id=document_b_id,
                section_id="summary",
                heading_title="Summary",
                heading_level=1,
                sequence=1,
                section_text="Validated content.",
            )
            session.add(section)
            session.flush()
            section_id = section.id
    finally:
        database.dispose()

    assert _upgrade_to_head_directly(settings.database_path)
    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            assert session.get(ReferenceAsset, document_b_id) is not None
            assert session.get(DocumentBSection, section_id) is not None
    finally:
        database.dispose()


def test_concurrent_historical_imports_are_serialized(tmp_path: Path) -> None:
    settings = legacy_settings(tmp_path)
    text = "Concurrent historical content."
    asset = _legacy_prompt(
        asset_key="assessment",
        version=1,
        text=text,
        is_active=True,
    )
    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            session.add(asset)
            session.flush()
            asset_id = asset.id
        path = _write_legacy_prompt(settings, asset, text)
    finally:
        database.dispose()

    initialize_database(settings.database_path)

    def migrate_once() -> tuple[int, int]:
        local_database = create_database(settings.database_path)
        try:
            result = PromptContentMigrationService(local_database, settings).migrate()
            return result.imported_version_count, result.removed_legacy_file_count
        finally:
            local_database.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: migrate_once(), range(2)))

    assert sum(imported for imported, _ in results) == 1
    assert sum(removed for _, removed in results) == 1
    assert not path.exists()
    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            stored = session.get(ReferenceAsset, asset_id)
            assert stored is not None
            assert stored.file_path is None
            content = session.get(PromptContent, asset_id)
            assert content is not None
            assert content.content == text
    finally:
        database.dispose()


def test_reset_imports_and_removes_historical_prompt_files(tmp_path: Path) -> None:
    settings = legacy_settings(tmp_path)
    text = "Prompt that must not remain after reset."
    asset = _legacy_prompt(
        asset_key="assessment",
        version=1,
        text=text,
        is_active=True,
    )
    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            session.add(asset)
        path = _write_legacy_prompt(settings, asset, text)
    finally:
        database.dispose()

    database = _upgrade_and_open(settings)
    try:
        result = ReferenceAssetResetService(database, settings).reset()

        assert result.reference_asset_count == 1
        assert result.local_file_count == 1
        assert not path.exists()
        with database.session() as session:
            assert session.get(ReferenceAsset, asset.id) is None
            assert session.get(PromptContent, asset.id) is None
    finally:
        database.dispose()


def test_downgrade_refuses_after_prompt_text_has_been_retained(tmp_path: Path) -> None:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        PromptService(database).save_text("assessment", "Retained SQLite prompt.")
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))

        with pytest.raises(RuntimeError, match="Cannot downgrade prompt-content storage"):
            with database.engine.connect() as connection:
                config.attributes["connection"] = connection
                command.downgrade(config, LEGACY_PROMPT_REVISION)

        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(PromptContent)) == 1
    finally:
        database.dispose()
