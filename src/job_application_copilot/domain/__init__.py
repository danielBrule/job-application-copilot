"""Application domain types."""

from job_application_copilot.domain.job import (
    CreateJob,
    JobFilters,
    Language,
    Location,
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

__all__ = [
    "CreateJob",
    "CreatePromptDefinition",
    "JobFilters",
    "Language",
    "Location",
    "PromptCompleteness",
    "ReferenceAssetProcessingStatus",
    "ReferenceAssetType",
    "UpdateJob",
    "UserDecision",
]
