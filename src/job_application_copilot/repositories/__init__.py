"""Database repositories and persistence infrastructure."""

from job_application_copilot.repositories.database import (
    Database,
    DatabaseHealth,
    create_database,
    create_database_url,
)
from job_application_copilot.repositories.job_repository import (
    DuplicateJobUrlError,
    JobNotFoundError,
    JobRepository,
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
    "Database",
    "DatabaseHealth",
    "DuplicateJobUrlError",
    "JobNotFoundError",
    "JobRepository",
    "PromptDefinitionNotFoundError",
    "PromptDefinitionRepository",
    "ReferenceAssetVersionNotFoundError",
    "ReferenceAssetRepository",
    "create_database",
    "create_database_url",
]
