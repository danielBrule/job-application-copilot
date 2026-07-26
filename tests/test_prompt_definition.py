"""Integration tests for prompt-definition persistence and migration."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import PromptDefinition
from job_application_copilot.repositories.prompt_definition_repository import (
    PromptDefinitionNotFoundError,
    PromptDefinitionRepository,
)
from job_application_copilot.services.database_bootstrap import (
    MIGRATIONS_DIRECTORY,
    initialize_database,
)

REFERENCE_ASSET_REVISION = "0003_create_reference_assets_table"
PROMPT_DEFINITION_REVISION = "0004_create_prompt_definitions"


@pytest.fixture
def migrated_database(tmp_path: Path) -> Database:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database
    finally:
        database.dispose()


def test_migration_seeds_initial_data_driven_definitions(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        definitions = PromptDefinitionRepository(session).list()

    assert [
        (
            definition.asset_key,
            definition.pipeline_group,
            definition.language_code,
            definition.position,
            definition.is_enabled,
        )
        for definition in definitions
    ] == [
        ("assessment", "assessment", None, 1, True),
        ("cv-generation-en-stage-1", "generation/english", "en", 1, True),
        ("cv-generation-en-stage-2", "generation/english", "en", 2, True),
        ("cv-generation-en-stage-3", "generation/english", "en", 3, True),
        ("cv-generation-en-stage-4", "generation/english", "en", 4, True),
        ("cv-generation-fr-extension-1", "generation/french", "fr", 1, True),
        ("cv-generation-fr-extension-2", "generation/french", "fr", 2, True),
    ]
    assert all(definition.created_at.microsecond == 0 for definition in definitions)


def test_repository_adds_and_orders_another_language_without_enum_change(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        repository = PromptDefinitionRepository(session)
        repository.add(
            PromptDefinition(
                asset_key="cv-generation-de-stage-2",
                name="German generation prompt 2",
                pipeline_group="generation/german",
                language_code="de",
                position=2,
            )
        )
        repository.add(
            PromptDefinition(
                asset_key="cv-generation-de-stage-1",
                name="German generation prompt 1",
                pipeline_group="generation/german",
                language_code="de",
                position=1,
            )
        )

    with migrated_database.session() as session:
        german = [
            definition
            for definition in PromptDefinitionRepository(session).list()
            if definition.pipeline_group == "generation/german"
        ]

    assert [definition.asset_key for definition in german] == [
        "cv-generation-de-stage-1",
        "cv-generation-de-stage-2",
    ]


def test_repository_filters_disabled_definitions(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        definition = PromptDefinitionRepository(session).require("cv-generation-en-stage-4")
        definition.is_enabled = False

    with migrated_database.session() as session:
        enabled = PromptDefinitionRepository(session).list(enabled_only=True)

    assert "cv-generation-en-stage-4" not in {definition.asset_key for definition in enabled}


def test_repository_reports_missing_definition(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        with pytest.raises(PromptDefinitionNotFoundError, match="does not exist"):
            PromptDefinitionRepository(session).require("unknown")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_key", " "),
        ("name", ""),
        ("pipeline_group", " "),
        ("language_code", ""),
        ("language_code", "FR"),
        ("position", 0),
    ],
)
def test_database_rejects_invalid_definition_values(
    migrated_database: Database,
    field: str,
    value: object,
) -> None:
    definition = PromptDefinition(
        asset_key="new-prompt",
        name="New prompt",
        pipeline_group="new-group",
        language_code="en",
        position=1,
    )
    setattr(definition, field, value)

    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.add(definition)


def test_database_rejects_duplicate_group_position(
    migrated_database: Database,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.add(
                PromptDefinition(
                    asset_key="another-assessment",
                    name="Another assessment prompt",
                    pipeline_group="assessment",
                    position=1,
                )
            )


def test_migration_schema_and_reversible_upgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "copilot.db"
    status = initialize_database(database_path)
    database = create_database(database_path)

    try:
        inspector = inspect(database.engine)
        columns = {column["name"]: column for column in inspector.get_columns("prompt_definitions")}
        checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("prompt_definitions")
        }
        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("prompt_definitions")
        }

        assert status.current_revision == PROMPT_DEFINITION_REVISION
        assert set(columns) == {
            "asset_key",
            "name",
            "pipeline_group",
            "language_code",
            "position",
            "is_enabled",
            "created_at",
            "updated_at",
        }
        assert columns["asset_key"]["primary_key"]
        assert columns["is_enabled"]["default"] is not None
        assert {
            "ck_prompt_definitions_key_not_blank",
            "ck_prompt_definitions_name_not_blank",
            "ck_prompt_definitions_group_not_blank",
            "ck_prompt_definitions_language_not_blank",
            "ck_prompt_definitions_language_lowercase",
            "ck_prompt_definitions_position_positive",
        } <= checks
        assert "uq_prompt_definitions_group_position" in unique_constraints

        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, REFERENCE_ASSET_REVISION)

        assert "prompt_definitions" not in inspect(database.engine).get_table_names()
        assert "reference_assets" in inspect(database.engine).get_table_names()
    finally:
        database.dispose()

    upgraded = initialize_database(database_path)
    assert upgraded.previous_revision == REFERENCE_ASSET_REVISION
    assert upgraded.current_revision == PROMPT_DEFINITION_REVISION
