"""Application domain types."""

from job_application_copilot.domain.job import (
    CreateJob,
    JobFilters,
    Language,
    Location,
    UpdateJob,
    UserDecision,
)
from job_application_copilot.domain.reference_asset import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)

__all__ = [
    "CreateJob",
    "JobFilters",
    "Language",
    "Location",
    "ReferenceAssetProcessingStatus",
    "ReferenceAssetType",
    "UpdateJob",
    "UserDecision",
]
