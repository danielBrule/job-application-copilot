"""Unit tests for the OpenAI Files API wrapper."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from job_application_copilot.config import AppSettings
from job_application_copilot.llm import (
    OpenAIConfigurationError,
    OpenAIFileClient,
    OpenAIFileClientError,
)
from job_application_copilot.llm.openai_client import (
    DOCX_MEDIA_TYPE,
    OPENAI_FILE_PURPOSE,
)


def make_client() -> tuple[OpenAIFileClient, Mock]:
    sdk_client = Mock()
    return OpenAIFileClient(cast(OpenAI, sdk_client)), sdk_client


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

    client.delete("file_123")
    client.close()

    sdk_client.files.delete.assert_called_once_with("file_123")
    sdk_client.close.assert_called_once_with()


@pytest.mark.parametrize("api_key", [None, "", "  "])
def test_requires_configured_api_key(api_key: str | None) -> None:
    with pytest.raises(OpenAIConfigurationError, match="OPENAI_API_KEY"):
        OpenAIFileClient.from_settings(AppSettings(_env_file=None, openai_api_key=api_key))


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

    with pytest.raises(OpenAIFileClientError, match=expected_message) as raised:
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

    with pytest.raises(OpenAIFileClientError, match=expected_message) as raised:
        client.upload_docx(filename="document.docx", content=b"content")

    assert raised.value.retryable is retryable
    assert raised.value.request_id == "req_failure"
    assert "sensitive provider response" not in str(raised.value)
