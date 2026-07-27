"""Application services."""

from job_application_copilot.repositories import (
    DuplicateJobUrlError,
    JobNotFoundError,
)
from job_application_copilot.services.document_b_vector_store import (
    DocumentBVectorStoreError,
    DocumentBVectorStoreNotAllowedError,
    DocumentBVectorStoreService,
)
from job_application_copilot.services.job_service import JobService
from job_application_copilot.services.openai_file_upload import (
    OpenAIFileUploadError,
    OpenAIFileUploadNotAllowedError,
    OpenAIFileUploadService,
    ReferenceAssetIntegrityError,
)
from job_application_copilot.services.prompt_service import (
    DuplicatePromptContentError,
    DuplicatePromptDefinitionError,
    PromptActivationError,
    PromptService,
    PromptStorageError,
)
from job_application_copilot.services.reference_asset_overview import (
    ReferenceAssetOverviewService,
)
from job_application_copilot.services.reference_asset_storage import (
    DuplicateReferenceAssetError,
    ReferenceAssetStorageError,
    ReferenceAssetStorageService,
    ReferenceExampleNotFoundError,
    UnsupportedReferenceAssetError,
)

__all__ = [
    "DuplicateJobUrlError",
    "DuplicatePromptContentError",
    "DuplicatePromptDefinitionError",
    "DuplicateReferenceAssetError",
    "DocumentBVectorStoreError",
    "DocumentBVectorStoreNotAllowedError",
    "DocumentBVectorStoreService",
    "JobNotFoundError",
    "JobService",
    "OpenAIFileUploadError",
    "OpenAIFileUploadNotAllowedError",
    "OpenAIFileUploadService",
    "PromptActivationError",
    "PromptService",
    "PromptStorageError",
    "ReferenceAssetStorageError",
    "ReferenceAssetOverviewService",
    "ReferenceAssetIntegrityError",
    "ReferenceExampleNotFoundError",
    "ReferenceAssetStorageService",
    "UnsupportedReferenceAssetError",
]
