"""Application domain types."""

from job_application_copilot.domain.assessment import (
    ASSESSMENT_SCHEMA_VERSION,
    AssessmentDecision,
    AssessmentEvidenceAnchor,
    AssessmentOutput,
    AssessmentStatus,
    assessment_output_json_schema,
)
from job_application_copilot.domain.background_run import (
    BackgroundAttemptSummary,
    BackgroundRunFilters,
    BackgroundRunSummary,
)
from job_application_copilot.domain.background_task import (
    BackgroundOperation,
    BackgroundTaskStatus,
    is_valid_background_task_transition,
)
from job_application_copilot.domain.document_b_retrieval import (
    DocumentBRetrievalRequest,
    DocumentBRetrievedPassage,
)
from job_application_copilot.domain.document_b_routing import (
    DocumentBRouteRole,
    DocumentBRoutingSetStatus,
    LaneId,
    RouteDeliveryMode,
    RouteInclusion,
    SecondaryLaneDisposition,
)
from job_application_copilot.domain.job import (
    CreateJob,
    CvSelectionStatus,
    JobFilters,
    Language,
    Location,
    Relevance,
    UpdateJob,
    UserDecision,
)
from job_application_copilot.domain.llm_call import (
    LlmCallStatus,
    LlmFailureCategory,
    LlmUsageTotals,
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
    "ASSESSMENT_SCHEMA_VERSION",
    "AssessmentDecision",
    "AssessmentEvidenceAnchor",
    "AssessmentOutput",
    "AssessmentStatus",
    "assessment_output_json_schema",
    "BackgroundOperation",
    "BackgroundAttemptSummary",
    "BackgroundRunFilters",
    "BackgroundRunSummary",
    "BackgroundTaskStatus",
    "CreateJob",
    "CvSelectionStatus",
    "CreatePromptDefinition",
    "DOCUMENT_A_KEY",
    "DOCUMENT_B_KEY",
    "DocumentBRouteRole",
    "DocumentBRoutingSetStatus",
    "DocumentBRetrievalRequest",
    "DocumentBRetrievedPassage",
    "ENGLISH_CV_TEMPLATE_KEY",
    "FRENCH_CV_TEMPLATE_KEY",
    "FrenchReferenceExamplesOverview",
    "JobFilters",
    "is_valid_background_task_transition",
    "Language",
    "LaneId",
    "Location",
    "LlmCallStatus",
    "LlmFailureCategory",
    "LlmUsageTotals",
    "Relevance",
    "PromptCompleteness",
    "REQUIRED_REFERENCE_ASSETS",
    "ReferenceAssetProcessingStatus",
    "ReferenceAssetType",
    "ReferenceAssetVersionSummary",
    "RouteInclusion",
    "RouteDeliveryMode",
    "RequiredReferenceAsset",
    "RequiredReferenceAssetOverview",
    "SettingsAssetOverview",
    "SecondaryLaneDisposition",
    "UpdateJob",
    "UserDecision",
]
