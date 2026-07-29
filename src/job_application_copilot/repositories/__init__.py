"""Database repositories and persistence infrastructure."""

from job_application_copilot.repositories.background_task_repository import (
    BackgroundBatchNotFoundError,
    BackgroundBatchRepository,
    BackgroundRunRepository,
    BackgroundTaskBatchOperationMismatchError,
    BackgroundTaskNotFoundError,
    BackgroundTaskRepository,
    InvalidBackgroundTaskTransitionError,
)
from job_application_copilot.repositories.database import (
    Database,
    DatabaseHealth,
    create_database,
    create_database_url,
)
from job_application_copilot.repositories.document_b_routing_repository import (
    DocumentBRoutingRepository,
)
from job_application_copilot.repositories.document_b_section_repository import (
    DocumentBSectionNotFoundError,
    DocumentBSectionRepository,
)
from job_application_copilot.repositories.job_repository import (
    DuplicateJobUrlError,
    JobNotFoundError,
    JobRepository,
)
from job_application_copilot.repositories.llm_call_repository import (
    LlmCallAssociationError,
    LlmCallRepository,
)
from job_application_copilot.repositories.prompt_definition_repository import (
    PromptDefinitionNotFoundError,
    PromptDefinitionRepository,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
    ReferenceAssetVersionNotFoundError,
)

__all__ = [
    "BackgroundBatchNotFoundError",
    "BackgroundBatchRepository",
    "BackgroundRunRepository",
    "BackgroundTaskBatchOperationMismatchError",
    "BackgroundTaskNotFoundError",
    "BackgroundTaskRepository",
    "Database",
    "DatabaseHealth",
    "DocumentBSectionNotFoundError",
    "DocumentBSectionRepository",
    "DocumentBRoutingRepository",
    "DuplicateJobUrlError",
    "JobNotFoundError",
    "JobRepository",
    "InvalidBackgroundTaskTransitionError",
    "LlmCallAssociationError",
    "LlmCallRepository",
    "PromptDefinitionNotFoundError",
    "PromptDefinitionRepository",
    "ReferenceAssetVersionNotFoundError",
    "ReferenceAssetRepository",
    "create_database",
    "create_database_url",
]
