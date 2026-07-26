"""Tests for the Settings reference-asset overview read model."""

from datetime import datetime
from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    CreatePromptDefinition,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.services import PromptService, ReferenceAssetOverviewService
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def overview_service(
    tmp_path: Path,
) -> tuple[ReferenceAssetOverviewService, PromptService, Database, AppSettings]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    prompt_service = PromptService(database, settings)
    try:
        yield (
            ReferenceAssetOverviewService(
                database,
                prompt_service,
                settings.minimum_french_reference_examples,
            ),
            prompt_service,
            database,
            settings,
        )
    finally:
        database.dispose()


def make_asset(
    *,
    asset_key: str,
    asset_type: ReferenceAssetType,
    name: str,
    version: int = 1,
    language_code: str | None = None,
    processing_status: ReferenceAssetProcessingStatus = (ReferenceAssetProcessingStatus.READY),
    is_active: bool = False,
    uploaded_at: datetime = datetime(2026, 7, 26, 11, 30, 45),
) -> ReferenceAsset:
    return ReferenceAsset(
        asset_key=asset_key,
        asset_type=asset_type,
        name=name,
        language_code=language_code,
        version=version,
        file_path=f"overview/{asset_key}-v{version:04d}.docx",
        file_hash=f"hash-{asset_key}-{version}",
        processing_status=processing_status,
        is_active=is_active,
        uploaded_at=uploaded_at,
        updated_at=uploaded_at,
    )


def test_empty_overview_keeps_all_required_categories_visible(
    overview_service: tuple[
        ReferenceAssetOverviewService,
        PromptService,
        Database,
        AppSettings,
    ],
) -> None:
    service, _, _, _ = overview_service

    overview = service.get_overview()

    assert [
        (item.requirement.asset_key, item.active_version, item.latest_version)
        for item in overview.required_assets
    ] == [
        ("document-a", None, None),
        ("document-b", None, None),
        ("cv-template-en", None, None),
        ("cv-template-fr", None, None),
    ]
    assert overview.french_examples.ready_count == 0
    assert overview.french_examples.minimum_required == 2
    assert not overview.french_examples.is_ready
    assert [
        (group.pipeline_group, group.ready_count, group.required_count)
        for group in overview.prompt_groups
    ] == [
        ("assessment", 0, 1),
        ("generation/english", 0, 4),
        ("generation/french", 0, 2),
    ]


def test_shows_active_version_and_newer_failed_candidate(
    overview_service: tuple[
        ReferenceAssetOverviewService,
        PromptService,
        Database,
        AppSettings,
    ],
) -> None:
    service, _, database, _ = overview_service
    with database.session() as session:
        session.add_all(
            [
                make_asset(
                    asset_key="document-a",
                    asset_type=ReferenceAssetType.DOCUMENT,
                    name="Document A",
                    version=1,
                    is_active=True,
                ),
                make_asset(
                    asset_key="document-a",
                    asset_type=ReferenceAssetType.DOCUMENT,
                    name="Document A replacement",
                    version=2,
                    processing_status=ReferenceAssetProcessingStatus.FAILED,
                ),
            ]
        )

    document_a = service.get_overview().required_assets[0]

    assert document_a.is_ready
    assert document_a.active_version is not None
    assert document_a.active_version.version == 1
    assert document_a.active_version.filename == "document-a-v0001.docx"
    assert document_a.latest_version is not None
    assert document_a.latest_version.version == 2
    assert document_a.latest_version.processing_status is ReferenceAssetProcessingStatus.FAILED


def test_shows_latest_pending_candidate_when_no_active_version_exists(
    overview_service: tuple[
        ReferenceAssetOverviewService,
        PromptService,
        Database,
        AppSettings,
    ],
) -> None:
    service, _, database, _ = overview_service
    with database.session() as session:
        session.add(
            make_asset(
                asset_key="document-b",
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document B",
                processing_status=ReferenceAssetProcessingStatus.PENDING,
            )
        )

    document_b = service.get_overview().required_assets[1]

    assert not document_b.is_ready
    assert document_b.active_version is None
    assert document_b.latest_version is not None
    assert document_b.latest_version.processing_status is ReferenceAssetProcessingStatus.PENDING


@pytest.mark.parametrize(("example_count", "is_ready"), [(1, False), (2, True), (3, True)])
def test_french_examples_use_minimum_count_without_fixed_keys(
    overview_service: tuple[
        ReferenceAssetOverviewService,
        PromptService,
        Database,
        AppSettings,
    ],
    example_count: int,
    is_ready: bool,
) -> None:
    service, _, database, _ = overview_service
    with database.session() as session:
        session.add_all(
            [
                make_asset(
                    asset_key=f"french-example-{index}",
                    asset_type=ReferenceAssetType.REFERENCE_EXAMPLE,
                    name=f"French example {index}",
                    language_code="fr",
                    is_active=True,
                )
                for index in range(1, example_count + 1)
            ]
        )

    examples = service.get_overview().french_examples

    assert examples.ready_count == example_count
    assert examples.is_ready is is_ready
    assert [item.asset_key for item in examples.active_versions] == [
        f"french-example-{index}" for index in range(1, example_count + 1)
    ]


def test_french_example_minimum_uses_configured_value(
    overview_service: tuple[
        ReferenceAssetOverviewService,
        PromptService,
        Database,
        AppSettings,
    ],
) -> None:
    _, prompts, database, _ = overview_service
    service = ReferenceAssetOverviewService(
        database,
        prompts,
        minimum_french_reference_examples=3,
    )
    with database.session() as session:
        session.add_all(
            [
                make_asset(
                    asset_key=f"french-example-{index}",
                    asset_type=ReferenceAssetType.REFERENCE_EXAMPLE,
                    name=f"French example {index}",
                    language_code="fr",
                    is_active=True,
                )
                for index in range(1, 3)
            ]
        )

    examples = service.get_overview().french_examples

    assert examples.minimum_required == 3
    assert examples.ready_count == 2
    assert not examples.is_ready


def test_prompt_groups_remain_data_driven_in_combined_overview(
    overview_service: tuple[
        ReferenceAssetOverviewService,
        PromptService,
        Database,
        AppSettings,
    ],
) -> None:
    service, prompts, _, _ = overview_service
    prompts.set_enabled("assessment", False)
    prompts.create_definition(
        CreatePromptDefinition(
            asset_key="cv-generation-de-stage-1",
            name="German generation prompt 1",
            pipeline_group="generation/german",
            language_code="de",
            position=1,
        )
    )
    prompts.save_text("cv-generation-de-stage-1", "German prompt")

    groups = {group.pipeline_group: group for group in service.get_overview().prompt_groups}

    assert "assessment" not in groups
    assert groups["generation/german"].ready_count == 1
    assert groups["generation/german"].required_count == 1
    assert groups["generation/german"].is_ready
