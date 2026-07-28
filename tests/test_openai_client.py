"""Unit tests for the OpenAI Files API wrapper."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from job_application_copilot.config import AppSettings
from job_application_copilot.llm import (
    OpenAIClient,
    OpenAIClientError,
    OpenAIConfigurationError,
    OpenAIVectorStoreFileStatus,
    openai_client,
)
from job_application_copilot.llm.openai_client import (
    DOCX_MEDIA_TYPE,
    OPENAI_FILE_PURPOSE,
)


def make_client() -> tuple[OpenAIClient, Mock]:
    sdk_client = Mock()
    return OpenAIClient(cast(OpenAI, sdk_client)), sdk_client


def test_uploads_exact_docx_content_as_user_data() -> None:
    client, sdk_client = make_client()
    sdk_client.files.create.return_value = SimpleNamespace(
        id="file_123",
        filename="document-a-v0001.docx",
        bytes=12,
        _request_id="req_123",
    )

    result = client.upload_docx(
        filename="document-a-v0001.docx",
        content=b"docx content",
    )

    sdk_client.files.create.assert_called_once_with(
        file=("document-a-v0001.docx", b"docx content", DOCX_MEDIA_TYPE),
        purpose=OPENAI_FILE_PURPOSE,
    )
    assert result.file_id == "file_123"
    assert result.filename == "document-a-v0001.docx"
    assert result.size_bytes == 12
    assert result.request_id == "req_123"


def test_deletes_file_and_closes_sdk_client() -> None:
    client, sdk_client = make_client()

    client.delete_file("file_123")
    client.close()

    sdk_client.files.delete.assert_called_once_with("file_123")
    sdk_client.close.assert_called_once_with()


def test_creates_empty_vector_store_for_section_sources() -> None:
    client, sdk_client = make_client()
    sdk_client.vector_stores.create.return_value = SimpleNamespace(
        id="vs_123",
        status="in_progress",
        usage_bytes=0,
        _request_id="req_create",
    )

    result = client.create_vector_store(name="document-b-v0001")

    sdk_client.vector_stores.create.assert_called_once_with(name="document-b-v0001")
    assert result.vector_store_id == "vs_123"
    assert result.status == "in_progress"
    assert result.usage_bytes == 0
    assert result.request_id == "req_create"


def test_polls_vector_store_file_until_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sdk_client = make_client()
    sdk_client.vector_stores.files.retrieve.side_effect = [
        SimpleNamespace(
            id="file_b",
            vector_store_id="vs_123",
            status="in_progress",
            usage_bytes=0,
            last_error=None,
            _request_id="req_poll_1",
        ),
        SimpleNamespace(
            id="file_b",
            vector_store_id="vs_123",
            status="completed",
            usage_bytes=4_096,
            last_error=None,
            _request_id="req_poll_2",
        ),
    ]
    monkeypatch.setattr(openai_client.time, "monotonic", Mock(side_effect=[0.0, 1.0]))
    sleep = Mock()
    monkeypatch.setattr(openai_client.time, "sleep", sleep)

    result = client.wait_for_vector_store_file(
        vector_store_id="vs_123",
        file_id="file_b",
        timeout_seconds=30,
    )

    assert result.status is OpenAIVectorStoreFileStatus.COMPLETED
    assert result.usage_bytes == 4_096
    assert result.request_id == "req_poll_2"
    assert sdk_client.vector_stores.files.retrieve.call_count == 2
    sleep.assert_called_once_with(openai_client.OPENAI_VECTOR_STORE_POLL_INTERVAL_SECONDS)


def test_retries_transient_missing_vector_store_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sdk_client = make_client()
    request = httpx.Request(
        "GET",
        "https://api.openai.com/v1/vector_stores/vs_123/files/file_b",
    )
    response = httpx.Response(
        404,
        request=request,
        headers={"x-request-id": "req_missing"},
    )
    sdk_client.vector_stores.files.retrieve.side_effect = [
        APIStatusError(
            "attachment not propagated",
            response=response,
            body={"error": "attachment not propagated"},
        ),
        SimpleNamespace(
            id="file_b",
            vector_store_id="vs_123",
            status="completed",
            usage_bytes=4_096,
            last_error=None,
            _request_id="req_completed",
        ),
    ]
    monkeypatch.setattr(openai_client.time, "monotonic", Mock(side_effect=[0.0, 1.0]))
    sleep = Mock()
    monkeypatch.setattr(openai_client.time, "sleep", sleep)

    result = client.wait_for_vector_store_file(
        vector_store_id="vs_123",
        file_id="file_b",
        timeout_seconds=30,
    )

    assert result.status is OpenAIVectorStoreFileStatus.COMPLETED
    assert sdk_client.vector_stores.files.retrieve.call_count == 2
    sleep.assert_called_once_with(openai_client.OPENAI_VECTOR_STORE_POLL_INTERVAL_SECONDS)


def test_vector_store_poll_times_out_at_overall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sdk_client = make_client()
    sdk_client.vector_stores.files.retrieve.return_value = SimpleNamespace(
        id="file_b",
        vector_store_id="vs_123",
        status="in_progress",
        usage_bytes=0,
        last_error=None,
        _request_id="req_poll",
    )
    monkeypatch.setattr(openai_client.time, "monotonic", Mock(side_effect=[0.0, 30.0]))
    monkeypatch.setattr(openai_client.time, "sleep", Mock())

    with pytest.raises(OpenAIClientError, match="within 30 seconds") as raised:
        client.wait_for_vector_store_file(
            vector_store_id="vs_123",
            file_id="file_b",
            timeout_seconds=30,
        )

    assert raised.value.operation == "vector_store_poll"
    assert raised.value.retryable
    assert raised.value.request_id == "req_poll"


def test_returns_safe_terminal_vector_store_failure() -> None:
    client, sdk_client = make_client()
    sdk_client.vector_stores.files.retrieve.return_value = SimpleNamespace(
        id="file_b",
        vector_store_id="vs_123",
        status="failed",
        usage_bytes=12,
        last_error=SimpleNamespace(code="invalid_file", message="provider detail"),
        _request_id="req_failed",
    )

    result = client.wait_for_vector_store_file(
        vector_store_id="vs_123",
        file_id="file_b",
        timeout_seconds=30,
    )

    assert result.status is OpenAIVectorStoreFileStatus.FAILED
    assert result.error_code == "invalid_file"
    assert "provider detail" not in repr(result)


def test_searches_vector_store_and_returns_typed_chunks() -> None:
    client, sdk_client = make_client()
    sdk_client.vector_stores.search.return_value = SimpleNamespace(
        data=[
            SimpleNamespace(
                file_id="file_b",
                filename="document-b.docx",
                score=0.91,
                content=[
                    SimpleNamespace(type="text", text="First chunk"),
                    SimpleNamespace(type="text", text="Second chunk"),
                ],
            )
        ]
    )

    results = client.search_vector_store(
        vector_store_id="vs_123",
        query="positioning guidance",
    )

    sdk_client.vector_stores.search.assert_called_once_with(
        "vs_123",
        query="positioning guidance",
        max_num_results=1,
        rewrite_query=False,
    )
    assert len(results) == 1
    assert results[0].file_id == "file_b"
    assert results[0].text == "First chunk\nSecond chunk"


def test_deletes_vector_store() -> None:
    client, sdk_client = make_client()

    client.delete_vector_store("vs_123")

    sdk_client.vector_stores.delete.assert_called_once_with("vs_123")


@pytest.mark.parametrize(
    ("operation", "resource_id"),
    [
        ("file", "file_missing"),
        ("vector_store", "vs_missing"),
    ],
)
def test_remote_deletion_treats_missing_resource_as_already_deleted(
    operation: str,
    resource_id: str,
) -> None:
    client, sdk_client = make_client()
    request = httpx.Request("DELETE", f"https://api.openai.com/v1/{operation}/{resource_id}")
    response = httpx.Response(
        404,
        request=request,
        headers={"x-request-id": "req_missing"},
    )
    error = APIStatusError(
        "resource missing",
        response=response,
        body={"error": "resource missing"},
    )
    if operation == "file":
        sdk_client.files.delete.side_effect = error
        client.delete_file(resource_id)
    else:
        sdk_client.vector_stores.delete.side_effect = error
        client.delete_vector_store(resource_id)


@pytest.mark.parametrize("api_key", [None, "", "  "])
def test_requires_configured_api_key(api_key: str | None) -> None:
    with pytest.raises(OpenAIConfigurationError, match="OPENAI_API_KEY"):
        OpenAIClient.from_settings(AppSettings(_env_file=None, openai_api_key=api_key))


@pytest.mark.parametrize(
    ("error", "expected_message", "retryable"),
    [
        (
            APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/files")),
            "timed out",
            True,
        ),
        (
            APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/files")),
            "could not be reached",
            True,
        ),
    ],
)
def test_translates_transport_errors_without_sdk_details(
    error: Exception,
    expected_message: str,
    retryable: bool,
) -> None:
    client, sdk_client = make_client()
    sdk_client.files.create.side_effect = error

    with pytest.raises(OpenAIClientError, match=expected_message) as raised:
        client.upload_docx(filename="document.docx", content=b"content")

    assert raised.value.retryable is retryable
    assert raised.value.request_id is None


@pytest.mark.parametrize(
    ("status_code", "expected_message", "retryable"),
    [
        (401, "Check OPENAI_API_KEY", False),
        (403, "denied access", False),
        (429, "rate-limited", True),
        (500, "HTTP status 500", True),
        (400, "HTTP status 400", False),
    ],
)
def test_translates_status_errors(
    status_code: int,
    expected_message: str,
    retryable: bool,
) -> None:
    client, sdk_client = make_client()
    request = httpx.Request("POST", "https://api.openai.com/v1/files")
    response = httpx.Response(
        status_code,
        request=request,
        headers={"x-request-id": "req_failure"},
    )
    sdk_client.files.create.side_effect = APIStatusError(
        "sensitive provider response",
        response=response,
        body={"error": "sensitive provider response"},
    )

    with pytest.raises(OpenAIClientError, match=expected_message) as raised:
        client.upload_docx(filename="document.docx", content=b"content")

    assert raised.value.retryable is retryable
    assert raised.value.request_id == "req_failure"
    assert "sensitive provider response" not in str(raised.value)
