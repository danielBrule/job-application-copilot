"""Integration tests for reference-asset persistence and migration."""

from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.services.database_bootstrap import (
    MIGRATIONS_DIRECTORY,
    get_migration_head,
    initialize_database,
)

JOB_REVISION = "0002_create_jobs_table"
REFERENCE_ASSET_REVISION = "0003_create_reference_assets_table"


@pytest.fixture
def migrated_database(tmp_path: Path) -> Database:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database
    finally:
        database.dispose()


def make_asset(
    *,
    asset_key: str = "document-a",
    asset_type: ReferenceAssetType = ReferenceAssetType.DOCUMENT,
    name: str = "Document A",
    language_code: str | None = "en",
    version: int = 1,
    is_active: bool = False,
    processing_status: ReferenceAssetProcessingStatus = (ReferenceAssetProcessingStatus.READY),
) -> ReferenceAsset:
    return ReferenceAsset(
        asset_key=asset_key,
        asset_type=asset_type,
        name=name,
        language_code=language_code,
        version=version,
        file_path=f"document_a/{version}.docx",
        file_hash=f"hash-{asset_key}-{version}",
        is_active=is_active,
        processing_status=processing_status,
    )


def test_round_trips_metadata_and_internal_defaults(
    migrated_database: Database,
) -> None:
    asset = ReferenceAsset(
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
        language_code=None,
        version=2,
        file_path="document_b/document-b-v2.docx",
        file_hash="sha256-value",
        processing_status=ReferenceAssetProcessingStatus.PROCESSING,
        processing_error="Previous upload failed.",
        openai_file_id="file_123",
        openai_vector_store_id="vs_123",
        openai_vector_store_usage_bytes=8_192,
    )

    with migrated_database.session() as session:
        session.add(asset)
        session.flush()
        asset_id = asset.id

    with migrated_database.session() as session:
        stored = session.get(ReferenceAsset, asset_id)

        assert stored is not None
        assert stored.asset_type is ReferenceAssetType.DOCUMENT
        assert stored.processing_status is ReferenceAssetProcessingStatus.PROCESSING
        assert stored.language_code is None
        assert not stored.is_active
        assert stored.openai_file_id == "file_123"
        assert stored.openai_vector_store_id == "vs_123"
        assert stored.openai_vector_store_usage_bytes == 8_192
        assert stored.processing_error == "Previous upload failed."
        assert stored.uploaded_at.microsecond == 0
        assert stored.updated_at.microsecond == 0


def test_direct_insert_uses_pending_inactive_defaults(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        asset_id = session.scalar(
            text(
                """
                INSERT INTO reference_assets (
                    asset_key,
                    asset_type,
                    name,
                    version,
                    file_path,
                    file_hash
                )
                VALUES (
                    'assessment',
                    'PROMPT',
                    'Assessment prompt',
                    1,
                    'prompts/assessment/v1.txt',
                    'hash-v1'
                )
                RETURNING id
                """
            )
        )

    with migrated_database.session() as session:
        stored = session.get(ReferenceAsset, asset_id)

        assert stored is not None
        assert stored.processing_status is ReferenceAssetProcessingStatus.PENDING
        assert not stored.is_active
        assert isinstance(stored.uploaded_at, datetime)
        assert isinstance(stored.updated_at, datetime)


def test_retains_versions_and_enforces_one_active_version_per_asset_key(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        session.add_all(
            [
                make_asset(version=1),
                make_asset(version=2, is_active=True),
            ]
        )

    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.add(make_asset(version=3, is_active=True))


def test_supports_multiple_active_reference_examples(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        session.add_all(
            [
                make_asset(
                    asset_key="french-example-platform",
                    asset_type=ReferenceAssetType.REFERENCE_EXAMPLE,
                    name="French platform CV",
                    language_code="fr",
                    is_active=True,
                ),
                make_asset(
                    asset_key="french-example-leadership",
                    asset_type=ReferenceAssetType.REFERENCE_EXAMPLE,
                    name="French leadership CV",
                    language_code="fr",
                    is_active=True,
                ),
            ]
        )

    with migrated_database.session() as session:
        active_example_count = session.scalar(
            select(func.count())
            .select_from(ReferenceAsset)
            .where(
                ReferenceAsset.asset_type == ReferenceAssetType.REFERENCE_EXAMPLE,
                ReferenceAsset.is_active.is_(True),
            )
        )
        assert active_example_count == 2


def test_supports_data_driven_prompt_keys_and_language_codes(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        session.add_all(
            [
                make_asset(
                    asset_key="cv-generation-en-opening",
                    asset_type=ReferenceAssetType.PROMPT,
                    name="English opening stage",
                    language_code="en",
                    is_active=True,
                ),
                make_asset(
                    asset_key="cv-generation-de-adaptation",
                    asset_type=ReferenceAssetType.PROMPT,
                    name="German adaptation stage",
                    language_code="de",
                    is_active=True,
                ),
            ]
        )

    with migrated_database.session() as session:
        prompts = list(
            session.scalars(
                select(ReferenceAsset)
                .where(ReferenceAsset.asset_type == ReferenceAssetType.PROMPT)
                .order_by(ReferenceAsset.asset_key)
            )
        )

        assert [(prompt.asset_key, prompt.language_code) for prompt in prompts] == [
            ("cv-generation-de-adaptation", "de"),
            ("cv-generation-en-opening", "en"),
        ]


def test_rejects_duplicate_version_for_same_asset_key(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        session.add(make_asset())

    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.add(make_asset(name="Renamed Document A"))


@pytest.mark.parametrize(
    "processing_status",
    [
        ReferenceAssetProcessingStatus.PENDING,
        ReferenceAssetProcessingStatus.PROCESSING,
        ReferenceAssetProcessingStatus.FAILED,
    ],
)
def test_only_ready_version_can_be_active(
    migrated_database: Database,
    processing_status: ReferenceAssetProcessingStatus,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.add(
                make_asset(
                    is_active=True,
                    processing_status=processing_status,
                )
            )


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("asset_key", "  "),
        ("name", ""),
        ("language_code", " "),
        ("version", 0),
        ("file_path", ""),
        ("file_hash", " "),
        ("openai_file_id", ""),
        ("openai_vector_store_id", " "),
        ("openai_vector_store_usage_bytes", -1),
    ],
)
def test_rejects_invalid_constrained_values(
    migrated_database: Database,
    column: str,
    invalid_value: object,
) -> None:
    asset = make_asset()
    setattr(asset, column, invalid_value)

    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.add(asset)


def test_migration_schema_and_reversible_upgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "copilot.db"
    status = initialize_database(database_path)
    database = create_database(database_path)

    try:
        inspector = inspect(database.engine)
        columns = {column["name"]: column for column in inspector.get_columns("reference_assets")}
        checks = {
            constraint["name"] for constraint in inspector.get_check_constraints("reference_assets")
        }
        indexes = {index["name"]: index for index in inspector.get_indexes("reference_assets")}
        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("reference_assets")
        }

        assert status.current_revision == get_migration_head()
        assert set(columns) == {
            "id",
            "asset_key",
            "asset_type",
            "name",
            "language_code",
            "version",
            "file_path",
            "file_hash",
            "is_active",
            "processing_status",
            "openai_file_id",
            "openai_vector_store_id",
            "openai_vector_store_usage_bytes",
            "processing_error",
            "uploaded_at",
            "updated_at",
        }
        for field in (
            "asset_key",
            "asset_type",
            "name",
            "version",
            "file_path",
            "file_hash",
        ):
            assert not columns[field]["nullable"]
        assert columns["is_active"]["default"] is not None
        assert columns["processing_status"]["default"] is not None
        assert columns["uploaded_at"]["default"] is not None
        assert columns["updated_at"]["default"] is not None
        assert {
            "reference_asset_type",
            "reference_asset_processing_status",
            "ck_reference_assets_key_not_blank",
            "ck_reference_assets_name_not_blank",
            "ck_reference_assets_language_not_blank",
            "ck_reference_assets_version_positive",
            "ck_reference_assets_path_not_blank",
            "ck_reference_assets_hash_not_blank",
            "ck_reference_assets_openai_file_id_not_blank",
            "ck_reference_assets_vector_store_id_not_blank",
            "ck_reference_assets_vector_store_usage_bytes_non_negative",
            "ck_reference_assets_active_ready",
        } <= checks
        assert "uq_reference_assets_key_version" in unique_constraints
        assert indexes["uq_reference_assets_active_key"]["unique"]

        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, JOB_REVISION)

        assert inspect(database.engine).get_table_names() == [
            "alembic_version",
            "jobs",
        ]
    finally:
        database.dispose()

    upgraded = initialize_database(database_path)
    assert upgraded.previous_revision == JOB_REVISION
    assert upgraded.current_revision == get_migration_head()
