"""Small, typed wrapper around the OpenAI Files API."""

from __future__ import annotations

from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

from job_application_copilot.config import AppSettings

OPENAI_FILE_PURPOSE = "user_data"
OPENAI_FILE_UPLOAD_MAX_RETRIES = 2
OPENAI_FILE_UPLOAD_TIMEOUT_SECONDS = 120.0
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True, slots=True)
class UploadedOpenAIFile:
    """Stable application view of one OpenAI file-upload response."""

    file_id: str
    filename: str
    size_bytes: int
    request_id: str | None


class OpenAIConfigurationError(RuntimeError):
    """Raised when the OpenAI client cannot be configured safely."""


class OpenAIFileClientError(RuntimeError):
    """Safe, structured failure from an OpenAI file operation."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        retryable: bool,
        request_id: str | None = None,
    ) -> None:
        self.operation = operation
        self.retryable = retryable
        self.request_id = request_id
        super().__init__(message)


class OpenAIFileClient:
    """Upload and delete files through one configured OpenAI SDK client."""

    def __init__(self, sdk_client: OpenAI) -> None:
        self._sdk_client = sdk_client

    @classmethod
    def from_settings(cls, settings: AppSettings) -> OpenAIFileClient:
        """Create the SDK client without exposing the configured secret."""

        if settings.openai_api_key is None:
            raise OpenAIConfigurationError("OPENAI_API_KEY is required for OpenAI file operations.")
        api_key = settings.openai_api_key.get_secret_value().strip()
        if not api_key:
            raise OpenAIConfigurationError("OPENAI_API_KEY is required for OpenAI file operations.")
        return cls(
            OpenAI(
                api_key=api_key,
                max_retries=OPENAI_FILE_UPLOAD_MAX_RETRIES,
                timeout=OPENAI_FILE_UPLOAD_TIMEOUT_SECONDS,
            )
        )

    def upload_docx(self, *, filename: str, content: bytes) -> UploadedOpenAIFile:
        """Upload exact validated DOCX bytes using the flexible user-data purpose."""

        try:
            uploaded = self._sdk_client.files.create(
                file=(filename, content, DOCX_MEDIA_TYPE),
                purpose=OPENAI_FILE_PURPOSE,
            )
        except APIError as error:
            raise _translate_openai_error(error, operation="upload") from error

        return UploadedOpenAIFile(
            file_id=uploaded.id,
            filename=uploaded.filename,
            size_bytes=uploaded.bytes,
            request_id=uploaded._request_id,
        )

    def delete(self, file_id: str) -> None:
        """Delete one OpenAI file, primarily for failed-operation compensation."""

        try:
            self._sdk_client.files.delete(file_id)
        except APIError as error:
            raise _translate_openai_error(error, operation="delete") from error

    def close(self) -> None:
        """Close HTTP resources owned by the SDK client."""

        self._sdk_client.close()


def _translate_openai_error(
    error: APIError,
    *,
    operation: str,
) -> OpenAIFileClientError:
    if isinstance(error, APITimeoutError):
        return OpenAIFileClientError(
            "The OpenAI file request timed out after the configured retries.",
            operation=operation,
            retryable=True,
        )
    if isinstance(error, APIConnectionError):
        return OpenAIFileClientError(
            "OpenAI could not be reached after the configured retries.",
            operation=operation,
            retryable=True,
        )
    if isinstance(error, APIStatusError):
        status_code = error.status_code
        request_id = error.request_id
        retryable = status_code in {408, 409, 429} or status_code >= 500
        if status_code == 401:
            message = "OpenAI rejected the API key. Check OPENAI_API_KEY."
        elif status_code == 403:
            message = "OpenAI denied access to the Files API for this project."
        elif status_code == 429:
            message = "OpenAI rate-limited the file request after the configured retries."
        else:
            message = f"OpenAI rejected the file request with HTTP status {status_code}."
        return OpenAIFileClientError(
            message,
            operation=operation,
            retryable=retryable,
            request_id=request_id,
        )
    return OpenAIFileClientError(
        "The OpenAI SDK could not complete the file request.",
        operation=operation,
        retryable=False,
    )
