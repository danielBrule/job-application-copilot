"""Application services."""

from job_application_copilot.repositories import (
    DuplicateJobUrlError,
    JobNotFoundError,
)
from job_application_copilot.services.assessment_batch import (
    AssessmentBatchQueueResult,
    AssessmentBatchService,
    AssessmentQueueSkip,
    AssessmentQueueSkipReason,
)
from job_application_copilot.services.assessment_context import (
    AssessmentCacheIdentity,
    AssessmentContext,
    AssessmentContextBuilder,
    AssessmentContextError,
    AssessmentFileInput,
    AssessmentTextInput,
    AssessmentTraceability,
)
from job_application_copilot.services.assessment_execution import (
    AssessmentExecutionResult,
    AssessmentExecutionService,
)
from job_application_copilot.services.assessment_persistence import AssessmentPersistenceService
from job_application_copilot.services.assessment_worker_handler import (
    AssessmentTaskFailedError,
    AssessmentWorkerHandler,
)
from job_application_copilot.services.background_runs import BackgroundRunService
from job_application_copilot.services.cv_selection import (
    CvSelectionResult,
    CvSelectionService,
    CvSelectionSkip,
    CvSelectionSkipReason,
)
from job_application_copilot.services.default_assessment_prompt import (
    DefaultAssessmentPromptError,
    DefaultAssessmentPromptService,
)
from job_application_copilot.services.document_a_input import (
    DocumentAInput,
    DocumentAInputService,
    DocumentAInputUnavailableError,
    OpenAIInputFile,
)
from job_application_copilot.services.document_a_processing import (
    DocumentAProcessingError,
    DocumentAProcessingService,
)
from job_application_copilot.services.document_b_processing import (
    DocumentBProcessingError,
    DocumentBProcessingService,
)
from job_application_copilot.services.document_b_retrieval import (
    DocumentBRetrievalError,
    DocumentBRetrievalPacket,
    DocumentBRetrievalService,
)
from job_application_copilot.services.document_b_routing import (
    DocumentBRoutingError,
    DocumentBRoutingManifestService,
    ResolvedLanePacket,
    ResolvedRouteEntry,
    ResolvedRouting,
    RoutingSetSummary,
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
from job_application_copilot.services.job_service import (
    AssessmentReviewNavigation,
    AssessmentReviewNotEligibleError,
    CvLaneConfigurationError,
    InvalidCvLaneSelectionError,
    JobAssessmentDetail,
    JobService,
)
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
    PromptValidationError,
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
    ReferenceAssetValidationError,
    ReferenceExampleNotFoundError,
    UnsupportedReferenceAssetError,
)

__all__ = [
    "AssessmentCacheIdentity",
    "AssessmentBatchQueueResult",
    "AssessmentBatchService",
    "AssessmentContext",
    "AssessmentContextBuilder",
    "AssessmentContextError",
    "AssessmentExecutionResult",
    "AssessmentExecutionService",
    "AssessmentPersistenceService",
    "AssessmentTaskFailedError",
    "AssessmentQueueSkip",
    "AssessmentQueueSkipReason",
    "AssessmentReviewNavigation",
    "AssessmentReviewNotEligibleError",
    "AssessmentWorkerHandler",
    "AssessmentFileInput",
    "AssessmentTextInput",
    "AssessmentTraceability",
    "BackgroundRunService",
    "DocumentAInput",
    "DocumentAInputService",
    "DocumentAInputUnavailableError",
    "DocumentAProcessingError",
    "DocumentAProcessingService",
    "DuplicateJobUrlError",
    "DuplicatePromptContentError",
    "DuplicatePromptDefinitionError",
    "DuplicateReferenceAssetError",
    "DocumentBVectorStoreError",
    "DocumentBVectorStoreNotAllowedError",
    "DocumentBVectorStoreService",
    "DefaultAssessmentPromptError",
    "DefaultAssessmentPromptService",
    "DocumentBProcessingError",
    "DocumentBProcessingService",
    "DocumentBSectionError",
    "DocumentBSectionRecord",
    "DocumentBSectionService",
    "DocumentBRetrievalError",
    "DocumentBRetrievalPacket",
    "DocumentBRetrievalService",
    "DocumentBRoutingError",
    "DocumentBRoutingManifestService",
    "ResolvedLanePacket",
    "ResolvedRouteEntry",
    "ResolvedRouting",
    "RoutingSetSummary",
    "JobNotFoundError",
    "CvLaneConfigurationError",
    "CvSelectionResult",
    "CvSelectionService",
    "CvSelectionSkip",
    "CvSelectionSkipReason",
    "InvalidCvLaneSelectionError",
    "JobAssessmentDetail",
    "JobService",
    "OpenAIFileUploadError",
    "OpenAIFileUploadNotAllowedError",
    "OpenAIFileUploadService",
    "OpenAIInputFile",
    "PromptActivationError",
    "PromptService",
    "PromptStorageError",
    "PromptValidationError",
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
    "ReferenceAssetValidationError",
    "UnsupportedReferenceAssetError",
]
