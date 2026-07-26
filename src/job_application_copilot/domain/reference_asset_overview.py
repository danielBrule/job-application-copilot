"""Read-model values for the required Settings reference-asset overview."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from job_application_copilot.domain.prompt import PromptCompleteness
from job_application_copilot.domain.reference_asset import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)

DOCUMENT_A_KEY = "document-a"
DOCUMENT_B_KEY = "document-b"
ENGLISH_CV_TEMPLATE_KEY = "cv-template-en"
FRENCH_CV_TEMPLATE_KEY = "cv-template-fr"


@dataclass(frozen=True, slots=True)
class RequiredReferenceAsset:
    """Stable non-prompt input that must be visible even when missing."""

    asset_key: str
    label: str
    asset_type: ReferenceAssetType
    language_code: str | None = None


REQUIRED_REFERENCE_ASSETS = (
    RequiredReferenceAsset(
        asset_key=DOCUMENT_A_KEY,
        label="Document A",
        asset_type=ReferenceAssetType.DOCUMENT,
    ),
    RequiredReferenceAsset(
        asset_key=DOCUMENT_B_KEY,
        label="Document B",
        asset_type=ReferenceAssetType.DOCUMENT,
    ),
    RequiredReferenceAsset(
        asset_key=ENGLISH_CV_TEMPLATE_KEY,
        label="English CV template",
        asset_type=ReferenceAssetType.TEMPLATE,
        language_code="en",
    ),
    RequiredReferenceAsset(
        asset_key=FRENCH_CV_TEMPLATE_KEY,
        label="French CV template",
        asset_type=ReferenceAssetType.TEMPLATE,
        language_code="fr",
    ),
)


@dataclass(frozen=True, slots=True)
class ReferenceAssetVersionSummary:
    """Presentation-neutral metadata for one immutable reference-asset version."""

    id: int
    asset_key: str
    name: str
    filename: str
    version: int
    uploaded_at: datetime
    processing_status: ReferenceAssetProcessingStatus
    is_active: bool

    @classmethod
    def from_values(
        cls,
        *,
        id: int,
        asset_key: str,
        name: str,
        file_path: str,
        version: int,
        uploaded_at: datetime,
        processing_status: ReferenceAssetProcessingStatus,
        is_active: bool,
    ) -> "ReferenceAssetVersionSummary":
        return cls(
            id=id,
            asset_key=asset_key,
            name=name,
            filename=Path(file_path).name,
            version=version,
            uploaded_at=uploaded_at,
            processing_status=processing_status,
            is_active=is_active,
        )


@dataclass(frozen=True, slots=True)
class RequiredReferenceAssetOverview:
    """Active and latest-candidate state for one stable required asset."""

    requirement: RequiredReferenceAsset
    active_version: ReferenceAssetVersionSummary | None
    latest_version: ReferenceAssetVersionSummary | None

    @property
    def is_ready(self) -> bool:
        return self.active_version is not None


@dataclass(frozen=True, slots=True)
class FrenchReferenceExamplesOverview:
    """Dynamic French-example versions measured against the required minimum."""

    minimum_required: int
    active_versions: tuple[ReferenceAssetVersionSummary, ...]
    latest_versions: tuple[ReferenceAssetVersionSummary, ...]

    @property
    def ready_count(self) -> int:
        return len(self.active_versions)

    @property
    def is_ready(self) -> bool:
        return self.ready_count >= self.minimum_required


@dataclass(frozen=True, slots=True)
class SettingsAssetOverview:
    """Complete read model used to render required Settings inputs."""

    required_assets: tuple[RequiredReferenceAssetOverview, ...]
    french_examples: FrenchReferenceExamplesOverview
    prompt_groups: tuple[PromptCompleteness, ...]
