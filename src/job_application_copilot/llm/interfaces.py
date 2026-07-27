"""Capability-specific contracts for OpenAI reference-asset operations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from job_application_copilot.llm.openai_client import (
    OpenAIVectorStore,
    OpenAIVectorStoreFile,
    OpenAIVectorStoreSearchResult,
    UploadedOpenAIFile,
)


@runtime_checkable
class OpenAIFileOperations(Protocol):
    """File capabilities required by reference-document upload workflows."""

    def upload_docx(self, *, filename: str, content: bytes) -> UploadedOpenAIFile: ...

    def delete_file(self, file_id: str) -> None: ...


@runtime_checkable
class OpenAIVectorStoreOperations(Protocol):
    """Vector-store capabilities required by Document B processing."""

    def create_vector_store(self, *, name: str, file_id: str) -> OpenAIVectorStore: ...

    def wait_for_vector_store_file(
        self,
        *,
        vector_store_id: str,
        file_id: str,
        timeout_seconds: int,
    ) -> OpenAIVectorStoreFile: ...

    def search_vector_store(
        self,
        *,
        vector_store_id: str,
        query: str,
    ) -> tuple[OpenAIVectorStoreSearchResult, ...]: ...

    def delete_vector_store(self, vector_store_id: str) -> None: ...


@runtime_checkable
class OpenAIRemoteCleanupOperations(Protocol):
    """Deletion and lifecycle capabilities used by explicit cleanup commands."""

    def delete_vector_store(self, vector_store_id: str) -> None: ...

    def delete_file(self, file_id: str) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class OpenAIReferenceClient(
    OpenAIFileOperations,
    OpenAIVectorStoreOperations,
    OpenAIRemoteCleanupOperations,
    Protocol,
):
    """Complete reference-workflow client supplied by the production adapter."""
