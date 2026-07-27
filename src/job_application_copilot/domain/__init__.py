"""Application domain types."""

from job_application_copilot.domain.job import (
    CreateJob,
    JobFilters,
    Language,
    Location,
    Relevance,
    UpdateJob,
    UserDecision,
)
from job_application_copilot.domain.prompt import (
    CreatePromptDefinition,
    PromptCompleteness,
)
from job_application_copilot.domain.reference_asset import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.domain.reference_asset_overview import (
    DOCUMENT_A_KEY,
    DOCUMENT_B_KEY,
    ENGLISH_CV_TEMPLATE_KEY,
    FRENCH_CV_TEMPLATE_KEY,
    REQUIRED_REFERENCE_ASSETS,
    FrenchReferenceExamplesOverview,
    ReferenceAssetVersionSummary,
    RequiredReferenceAsset,
    RequiredReferenceAssetOverview,
    SettingsAssetOverview,
)

__all__ = [
    "CreateJob",
    "CreatePromptDefinition",
    "DOCUMENT_A_KEY",
    "DOCUMENT_B_KEY",
    "ENGLISH_CV_TEMPLATE_KEY",
    "FRENCH_CV_TEMPLATE_KEY",
    "FrenchReferenceExamplesOverview",
    "JobFilters",
    "Language",
    "Location",
    "Relevance",
    "PromptCompleteness",
    "REQUIRED_REFERENCE_ASSETS",
    "ReferenceAssetProcessingStatus",
    "ReferenceAssetType",
    "ReferenceAssetVersionSummary",
    "RequiredReferenceAsset",
    "RequiredReferenceAssetOverview",
    "SettingsAssetOverview",
    "UpdateJob",
    "UserDecision",
]
