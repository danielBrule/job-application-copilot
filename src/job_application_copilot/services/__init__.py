"""Application services."""

from job_application_copilot.repositories import (
    DuplicateJobUrlError,
    JobNotFoundError,
)
from job_application_copilot.services.job_service import JobService
from job_application_copilot.services.reference_asset_storage import (
    DuplicateReferenceAssetError,
    ReferenceAssetStorageError,
    ReferenceAssetStorageService,
    UnsupportedReferenceAssetError,
)

__all__ = [
    "DuplicateJobUrlError",
    "DuplicateReferenceAssetError",
    "JobNotFoundError",
    "JobService",
    "ReferenceAssetStorageError",
    "ReferenceAssetStorageService",
    "UnsupportedReferenceAssetError",
]
