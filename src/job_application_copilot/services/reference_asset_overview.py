"""Read-only aggregation for the Settings reference-asset overview."""

from itertools import groupby

from job_application_copilot.domain import (
    REQUIRED_REFERENCE_ASSETS,
    FrenchReferenceExamplesOverview,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
    ReferenceAssetVersionSummary,
    RequiredReferenceAsset,
    RequiredReferenceAssetOverview,
    SettingsAssetOverview,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.prompt_service import PromptService


class ReferenceAssetOverviewService:
    """Combine stable local requirements with persisted versions and prompt readiness."""

    def __init__(
        self,
        database: Database,
        prompt_service: PromptService,
        minimum_french_reference_examples: int,
    ) -> None:
        self.database = database
        self.prompt_service = prompt_service
        self.minimum_french_reference_examples = minimum_french_reference_examples

    def get_overview(self) -> SettingsAssetOverview:
        """Return active inputs, latest candidates, examples, and prompt groups."""

        with self.database.session() as session:
            repository = ReferenceAssetRepository(session)
            required_assets = tuple(
                self._required_overview(repository, requirement)
                for requirement in REQUIRED_REFERENCE_ASSETS
            )
            french_examples = self._french_examples_overview(repository)

        return SettingsAssetOverview(
            required_assets=required_assets,
            french_examples=french_examples,
            prompt_groups=self.prompt_service.completeness(),
        )

    @staticmethod
    def _required_overview(
        repository: ReferenceAssetRepository,
        requirement: RequiredReferenceAsset,
    ) -> RequiredReferenceAssetOverview:
        versions = [
            asset
            for asset in repository.list_versions(requirement.asset_key)
            if asset.asset_type is requirement.asset_type
            and (
                requirement.language_code is None
                or asset.language_code == requirement.language_code
            )
        ]
        active = next((asset for asset in versions if asset.is_active), None)
        latest = versions[0] if versions else None
        return RequiredReferenceAssetOverview(
            requirement=requirement,
            active_version=_summary(active),
            latest_version=_summary(latest),
        )

    def _french_examples_overview(
        self,
        repository: ReferenceAssetRepository,
    ) -> FrenchReferenceExamplesOverview:
        versions = repository.list_by_type(
            ReferenceAssetType.REFERENCE_EXAMPLE,
            language_code="fr",
        )
        latest_versions: list[ReferenceAsset] = []
        for _, grouped_versions in groupby(versions, key=lambda asset: asset.asset_key):
            latest_versions.append(next(grouped_versions))

        active_versions = [
            asset
            for asset in versions
            if asset.is_active and asset.processing_status is ReferenceAssetProcessingStatus.READY
        ]
        return FrenchReferenceExamplesOverview(
            minimum_required=self.minimum_french_reference_examples,
            active_versions=tuple(
                summary for asset in active_versions if (summary := _summary(asset)) is not None
            ),
            latest_versions=tuple(
                summary for asset in latest_versions if (summary := _summary(asset)) is not None
            ),
        )


def _summary(asset: ReferenceAsset | None) -> ReferenceAssetVersionSummary | None:
    if asset is None:
        return None
    if asset.file_path is None:
        raise RuntimeError(
            f"File-backed reference asset '{asset.asset_key}' version {asset.version} has no path."
        )
    return ReferenceAssetVersionSummary.from_values(
        id=asset.id,
        asset_key=asset.asset_key,
        name=asset.name,
        file_path=asset.file_path,
        version=asset.version,
        uploaded_at=asset.uploaded_at,
        processing_status=asset.processing_status,
        is_active=asset.is_active,
    )
