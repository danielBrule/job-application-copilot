"""Tests for Settings reference-asset overview presentation shaping."""

from datetime import datetime

from job_application_copilot.domain import (
    FrenchReferenceExamplesOverview,
    PromptCompleteness,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
    ReferenceAssetVersionSummary,
    RequiredReferenceAsset,
    RequiredReferenceAssetOverview,
    SettingsAssetOverview,
)
from job_application_copilot.ui.reference_asset_overview import (
    build_reference_asset_rows,
)


def summary(
    *,
    id: int,
    asset_key: str,
    version: int,
    status: ReferenceAssetProcessingStatus,
    active: bool,
) -> ReferenceAssetVersionSummary:
    return ReferenceAssetVersionSummary(
        id=id,
        asset_key=asset_key,
        name="Document A",
        filename=f"{asset_key}-v{version:04d}.docx",
        version=version,
        uploaded_at=datetime(2026, 7, 26, 11, 30, 45),
        processing_status=status,
        is_active=active,
    )


def test_shapes_missing_active_candidate_example_and_prompt_rows() -> None:
    active = summary(
        id=1,
        asset_key="document-a",
        version=1,
        status=ReferenceAssetProcessingStatus.READY,
        active=True,
    )
    failed = summary(
        id=2,
        asset_key="document-a",
        version=2,
        status=ReferenceAssetProcessingStatus.FAILED,
        active=False,
    )
    overview = SettingsAssetOverview(
        required_assets=(
            RequiredReferenceAssetOverview(
                requirement=RequiredReferenceAsset(
                    asset_key="document-a",
                    label="Document A",
                    asset_type=ReferenceAssetType.DOCUMENT,
                ),
                active_version=active,
                latest_version=failed,
            ),
            RequiredReferenceAssetOverview(
                requirement=RequiredReferenceAsset(
                    asset_key="document-b",
                    label="Document B",
                    asset_type=ReferenceAssetType.DOCUMENT,
                ),
                active_version=None,
                latest_version=None,
            ),
        ),
        french_examples=FrenchReferenceExamplesOverview(
            minimum_required=2,
            active_versions=(),
            latest_versions=(),
        ),
        prompt_groups=(
            PromptCompleteness(
                pipeline_group="generation/english",
                language_code="en",
                required_count=4,
                ready_count=3,
                missing_asset_keys=("cv-generation-en-stage-4",),
            ),
        ),
    )

    rows = build_reference_asset_rows(overview)

    assert [row.role for row in rows] == [
        "Active input",
        "Latest candidate",
        "Required input",
        "Requirement",
        "Required group",
    ]
    assert rows[0].as_dict() == {
        "Category": "Document A",
        "Asset key": "document-a",
        "Role": "Active input",
        "Name": "Document A",
        "Stored filename": "document-a-v0001.docx",
        "Version / count": "v1",
        "Uploaded": "2026-07-26 11:30:45 UTC",
        "Status": "READY",
        "Active": "Yes",
        "Details": "—",
    }
    assert rows[1].status == "FAILED — not active"
    assert rows[2].status == "MISSING"
    assert rows[3].version_or_count == "0/2"
    assert rows[3].details == "2 more ready example(s) required."
    assert rows[4].version_or_count == "3/4"
    assert rows[4].details == "Missing: cv-generation-en-stage-4"
