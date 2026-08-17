"""Tests for prompt definitions, private text versions, and completeness."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    CreatePromptDefinition,
    ReferenceAssetProcessingStatus,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import PromptContent, ReferenceAsset
from job_application_copilot.repositories.prompt_content_repository import (
    PromptContentRepository,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DuplicatePromptContentError,
    DuplicatePromptDefinitionError,
    PromptActivationError,
    PromptService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def prompt_service(
    tmp_path: Path,
) -> tuple[PromptService, Database, AppSettings]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        yield PromptService(database), database, settings
    finally:
        database.dispose()


def definition_command(
    *,
    asset_key: str = "cv-generation-de-stage-1",
    name: str = "German generation prompt 1",
    pipeline_group: str = "generation/german",
    language_code: str | None = "de",
    position: int = 1,
    is_enabled: bool = True,
) -> CreatePromptDefinition:
    return CreatePromptDefinition(
        asset_key=asset_key,
        name=name,
        pipeline_group=pipeline_group,
        language_code=language_code,
        position=position,
        is_enabled=is_enabled,
    )


def completeness_by_group(service: PromptService) -> dict[str, object]:
    return {group.pipeline_group: group for group in service.completeness()}


def test_initial_completeness_is_driven_by_seeded_enabled_definitions(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, _, _ = prompt_service

    groups = completeness_by_group(service)

    assert (groups["assessment"].ready_count, groups["assessment"].required_count) == (0, 1)
    assert groups["assessment"].missing_asset_keys == ("assessment",)
    assert (
        groups["generation/english"].ready_count,
        groups["generation/english"].required_count,
    ) == (0, 4)
    assert groups["generation/english"].missing_asset_keys == (
        "cv-generation-en-stage-1",
        "cv-generation-en-stage-2",
        "cv-generation-en-stage-3",
        "cv-generation-en-stage-4",
    )
    assert (
        groups["generation/french"].ready_count,
        groups["generation/french"].required_count,
    ) == (0, 2)


def test_saves_utf8_text_as_ready_active_immutable_versions(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, database, settings = prompt_service

    first = service.save_text("assessment", "Keep factual evidence.")
    second = service.save_text("assessment", "Préserver les preuves factuelles.\n")

    assert (first.version, second.version) == (1, 2)
    assert second.is_active
    assert second.processing_status is ReferenceAssetProcessingStatus.READY
    assert first.file_path is None
    assert second.file_path is None
    assert service.get_active_text("assessment") == "Préserver les preuves factuelles.\n"
    with database.session() as session:
        stored_versions = ReferenceAssetRepository(session).list_versions("assessment")
        assert [asset.version for asset in stored_versions] == [2, 1]
        assert not stored_versions[1].is_active
        assert sum(asset.is_active for asset in stored_versions) == 1
        first_content = PromptContentRepository(session).get(first.id)
        second_content = PromptContentRepository(session).get(second.id)
        assert first_content is not None
        assert second_content is not None
        assert first_content.content == "Keep factual evidence."
        assert second_content.content == "Préserver les preuves factuelles.\n"


def test_reactivates_retained_ready_version(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, _, _ = prompt_service
    service.save_text("assessment", "Version one")
    service.save_text("assessment", "Version two")

    activated = service.activate_version("assessment", 1)

    assert activated.version == 1
    assert activated.is_active
    assert service.get_active_text("assessment") == "Version one"
    assert [(asset.version, asset.is_active) for asset in service.list_versions("assessment")] == [
        (2, False),
        (1, True),
    ]


def test_completeness_tracks_ready_missing_and_disabled_definitions(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, _, _ = prompt_service
    service.save_text("cv-generation-en-stage-1", "English stage one")
    service.set_enabled("cv-generation-en-stage-4", False)

    english = completeness_by_group(service)["generation/english"]

    assert english.required_count == 3
    assert english.ready_count == 1
    assert english.missing_asset_keys == (
        "cv-generation-en-stage-2",
        "cv-generation-en-stage-3",
    )


def test_initial_configuration_reports_one_four_and_two_when_ready(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, _, _ = prompt_service
    for definition in service.list_definitions(enabled_only=True):
        service.save_text(definition.asset_key, f"Text for {definition.asset_key}")

    groups = completeness_by_group(service)

    assert (groups["assessment"].ready_count, groups["assessment"].required_count) == (1, 1)
    assert (
        groups["generation/english"].ready_count,
        groups["generation/english"].required_count,
    ) == (4, 4)
    assert (
        groups["generation/french"].ready_count,
        groups["generation/french"].required_count,
    ) == (2, 2)
    assert all(group.is_ready for group in groups.values())


def test_adds_new_group_language_and_prompt_count_without_schema_change(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, _, _ = prompt_service
    created = service.create_definition(
        CreatePromptDefinition.model_validate(
            {
                "asset_key": "cv-generation-de-stage-1",
                "name": " German generation prompt 1 ",
                "pipeline_group": "generation/german",
                "language_code": " DE ",
                "position": 1,
            }
        )
    )
    service.save_text(created.asset_key, "German stage one")

    german = completeness_by_group(service)["generation/german"]

    assert created.name == "German generation prompt 1"
    assert created.language_code == "de"
    assert german.language_code == "de"
    assert german.required_count == 1
    assert german.ready_count == 1
    assert german.missing_asset_keys == ()
    assert german.is_ready


def test_rejects_duplicate_definition_key_and_position(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, _, _ = prompt_service

    with pytest.raises(DuplicatePromptDefinitionError, match="already exists"):
        service.create_definition(
            definition_command(
                asset_key="assessment",
                pipeline_group="another-group",
            )
        )

    with pytest.raises(DuplicatePromptDefinitionError, match="already used"):
        service.create_definition(
            definition_command(
                asset_key="another-assessment",
                pipeline_group="assessment",
                language_code=None,
            )
        )


@pytest.mark.parametrize(
    "values",
    [
        {"asset_key": "Unsafe Key"},
        {"pipeline_group": "../outside"},
        {"language_code": "german_language_code"},
        {"position": 0},
    ],
)
def test_definition_boundary_rejects_invalid_dynamic_values(
    values: dict[str, object],
) -> None:
    command = {
        "asset_key": "new-prompt",
        "name": "New prompt",
        "pipeline_group": "new-group",
        "language_code": "en",
        "position": 1,
    }
    command.update(values)

    with pytest.raises(ValidationError):
        CreatePromptDefinition.model_validate(command)


def test_rejects_blank_and_duplicate_prompt_text(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, database, settings = prompt_service
    content = "Same prompt text"
    service.save_text("assessment", content)

    with pytest.raises(ValueError, match="must not be blank"):
        service.save_text("assessment", " \n ")
    with pytest.raises(DuplicatePromptContentError) as captured:
        service.save_text("assessment", content)

    assert captured.value.existing_version == 1
    assert not settings.legacy_prompts_folder.exists()
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceAsset)) == 1
        assert session.scalar(select(func.count()).select_from(PromptContent)) == 1


def test_rolls_back_prompt_text_when_metadata_write_fails(
    prompt_service: tuple[PromptService, Database, AppSettings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, database, settings = prompt_service

    def fail_add(
        repository: ReferenceAssetRepository,
        asset: ReferenceAsset,
    ) -> ReferenceAsset:
        del repository, asset
        raise RuntimeError("database write failed")

    monkeypatch.setattr(ReferenceAssetRepository, "add", fail_add)

    with pytest.raises(RuntimeError, match="database write failed"):
        service.save_text("assessment", "New prompt")

    assert not settings.legacy_prompts_folder.exists()
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceAsset)) == 0
        assert session.scalar(select(func.count()).select_from(PromptContent)) == 0


def test_rejects_activation_of_non_ready_version(
    prompt_service: tuple[PromptService, Database, AppSettings],
) -> None:
    service, database, _ = prompt_service
    saved = service.save_text("assessment", "Assessment prompt")
    with database.session() as session:
        stored = session.get(ReferenceAsset, saved.id)
        assert stored is not None
        stored.is_active = False
        stored.processing_status = ReferenceAssetProcessingStatus.FAILED

    with pytest.raises(PromptActivationError, match="not READY"):
        service.activate_version("assessment", 1)
