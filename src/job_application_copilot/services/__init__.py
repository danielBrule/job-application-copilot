"""Application services."""

from job_application_copilot.repositories import (
    DuplicateJobUrlError,
    JobNotFoundError,
)
from job_application_copilot.services.document_a_input import (
    DocumentAInput,
    DocumentAInputService,
    DocumentAInputUnavailableError,
    OpenAIInputFile,
)
from job_application_copilot.services.document_b_processing import (
    DocumentBProcessingError,
    DocumentBProcessingService,
)
from job_application_copilot.services.document_b_sections import (
    DocumentBSectionError,
    DocumentBSectionRecord,
    DocumentBSectionService,
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
from job_application_copilot.services.reference_asset_remote_cleanup import (
    InactiveRemoteAsset,
    ReferenceAssetRemoteCleanupError,
    ReferenceAssetRemoteCleanupNotAllowedError,
    ReferenceAssetRemoteCleanupResult,
    ReferenceAssetRemoteCleanupService,
    ReferenceAssetRemoteRestoreError,
    ReferenceAssetRemoteRestoreNotAllowedError,
)
from job_application_copilot.services.reference_asset_storage import (
    DuplicateReferenceAssetError,
    ReferenceAssetStorageError,
    ReferenceAssetStorageService,
    ReferenceExampleNotFoundError,
    UnsupportedReferenceAssetError,
)

__all__ = [
    "DocumentAInput",
    "DocumentAInputService",
    "DocumentAInputUnavailableError",
    "DuplicateJobUrlError",
    "DuplicatePromptContentError",
    "DuplicatePromptDefinitionError",
    "DuplicateReferenceAssetError",
    "DocumentBVectorStoreError",
    "DocumentBVectorStoreNotAllowedError",
    "DocumentBVectorStoreService",
    "DocumentBProcessingError",
    "DocumentBProcessingService",
    "DocumentBSectionError",
    "DocumentBSectionRecord",
    "DocumentBSectionService",
    "JobNotFoundError",
    "JobService",
    "OpenAIFileUploadError",
    "OpenAIFileUploadNotAllowedError",
    "OpenAIFileUploadService",
    "OpenAIInputFile",
    "PromptActivationError",
    "PromptService",
    "PromptStorageError",
    "ReferenceAssetStorageError",
    "ReferenceAssetOverviewService",
    "InactiveRemoteAsset",
    "ReferenceAssetRemoteCleanupError",
    "ReferenceAssetRemoteCleanupNotAllowedError",
    "ReferenceAssetRemoteCleanupResult",
    "ReferenceAssetRemoteCleanupService",
    "ReferenceAssetRemoteRestoreError",
    "ReferenceAssetRemoteRestoreNotAllowedError",
    "ReferenceAssetIntegrityError",
    "ReferenceExampleNotFoundError",
    "ReferenceAssetStorageService",
    "UnsupportedReferenceAssetError",
]
