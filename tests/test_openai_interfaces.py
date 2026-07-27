"""Contract tests for capability-specific OpenAI interfaces."""

from unittest.mock import Mock

from openai import OpenAI

from job_application_copilot.llm import (
    OpenAIClient,
    OpenAIFileOperations,
    OpenAIReferenceClient,
    OpenAIRemoteCleanupOperations,
    OpenAIVectorStore,
    OpenAIVectorStoreFile,
    OpenAIVectorStoreOperations,
    OpenAIVectorStoreSearchResult,
    UploadedOpenAIFile,
)


class FileOnlyClient:
    """Minimal fake implementing only reference-file operations."""

    def upload_docx(self, *, filename: str, content: bytes) -> UploadedOpenAIFile:
        return UploadedOpenAIFile(
            file_id="file_test",
            filename=filename,
            size_bytes=len(content),
            request_id=None,
        )

    def delete_file(self, file_id: str) -> None:
        del file_id


class VectorStoreOnlyClient:
    """Minimal fake implementing only Document B vector-store operations."""

    def create_vector_store(self, *, name: str, file_id: str) -> OpenAIVectorStore:
        del name, file_id
        return OpenAIVectorStore(
            vector_store_id="vs_test",
            status="completed",
            usage_bytes=0,
            request_id=None,
        )

    def wait_for_vector_store_file(
        self,
        *,
        vector_store_id: str,
        file_id: str,
        timeout_seconds: int,
    ) -> OpenAIVectorStoreFile:
        raise NotImplementedError

    def search_vector_store(
        self,
        *,
        vector_store_id: str,
        query: str,
    ) -> tuple[OpenAIVectorStoreSearchResult, ...]:
        del vector_store_id, query
        return ()

    def delete_vector_store(self, vector_store_id: str) -> None:
        del vector_store_id


def test_capability_protocols_accept_minimal_independent_fakes() -> None:
    file_client = FileOnlyClient()
    vector_client = VectorStoreOnlyClient()

    assert isinstance(file_client, OpenAIFileOperations)
    assert not isinstance(file_client, OpenAIVectorStoreOperations)
    assert isinstance(vector_client, OpenAIVectorStoreOperations)
    assert not isinstance(vector_client, OpenAIFileOperations)


def test_production_adapter_exposes_complete_reference_client_contract() -> None:
    client = OpenAIClient(Mock(spec=OpenAI))

    assert isinstance(client, OpenAIFileOperations)
    assert isinstance(client, OpenAIVectorStoreOperations)
    assert isinstance(client, OpenAIRemoteCleanupOperations)
    assert isinstance(client, OpenAIReferenceClient)
