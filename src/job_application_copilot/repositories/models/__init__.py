"""Registered SQLAlchemy persistence models."""

from job_application_copilot.repositories.models.document_b_retrieval import (
    DocumentBRetrievalTrace,
    DocumentBRetrievalTraceResult,
    DocumentBVectorRecord,
)
from job_application_copilot.repositories.models.document_b_routing import (
    DocumentBLaneRoute,
    DocumentBRoutingSet,
)
from job_application_copilot.repositories.models.document_b_section import (
    DocumentBSection,
)
from job_application_copilot.repositories.models.job import Job
from job_application_copilot.repositories.models.prompt_definition import PromptDefinition
from job_application_copilot.repositories.models.reference_asset import ReferenceAsset

__all__ = [
    "DocumentBLaneRoute",
    "DocumentBRoutingSet",
    "DocumentBSection",
    "DocumentBRetrievalTrace",
    "DocumentBRetrievalTraceResult",
    "DocumentBVectorRecord",
    "Job",
    "PromptDefinition",
    "ReferenceAsset",
]
