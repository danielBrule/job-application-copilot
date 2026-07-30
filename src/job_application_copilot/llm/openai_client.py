"""Small, typed wrapper around the OpenAI APIs used by the application."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, cast

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

from job_application_copilot.config import AppSettings

if TYPE_CHECKING:
    from job_application_copilot.services.assessment_context import AssessmentContext

OPENAI_FILE_PURPOSE: Literal["user_data"] = "user_data"
OPENAI_FILE_UPLOAD_MAX_RETRIES = 2
OPENAI_FILE_UPLOAD_TIMEOUT_SECONDS = 120.0
OPENAI_VECTOR_STORE_POLL_INTERVAL_SECONDS = 1.0
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_MEDIA_TYPE = "text/plain"


@dataclass(frozen=True, slots=True)
class UploadedOpenAIFile:
    """Stable application view of one OpenAI file-upload response."""

    file_id: str
    filename: str
    size_bytes: int
    request_id: str | None


@dataclass(frozen=True, slots=True)
class AssessmentOpenAIResponse:
    """Privacy-safe application view of one Responses API assessment result."""

    response_id: str
    request_id: str | None
    model: str | None
    output_text: str
    incomplete_reason: str | None
    service_tier: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    cache_mode: str | None
    cache_ttl: str | None


class OpenAIVectorStoreFileStatus(StrEnum):
    """Terminal and non-terminal indexing states returned by OpenAI."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class OpenAIVectorStore:
    """Stable application view of one OpenAI vector store."""

    vector_store_id: str
    status: str
    usage_bytes: int
    request_id: str | None


@dataclass(frozen=True, slots=True)
class OpenAIVectorStoreFile:
    """Stable application view of one file being indexed in a vector store."""

    file_id: str
    vector_store_id: str
    status: OpenAIVectorStoreFileStatus
    usage_bytes: int
    error_code: str | None
    request_id: str | None


@dataclass(frozen=True, slots=True)
class OpenAIVectorStoreSearchResult:
    """One retrievable chunk returned by direct vector-store search."""

    file_id: str
    filename: str
    score: float
    text: str
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)


class OpenAIConfigurationError(RuntimeError):
    """Raised when the OpenAI client cannot be configured safely."""


class OpenAIClientError(RuntimeError):
    """Safe, structured failure from an OpenAI operation."""

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


class OpenAIClient:
    """Perform application-authorised OpenAI operations through one SDK client."""

    def __init__(self, sdk_client: OpenAI) -> None:
        self._sdk_client = sdk_client

    @classmethod
    def from_settings(cls, settings: AppSettings) -> OpenAIClient:
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

    def assess(self, context: AssessmentContext) -> AssessmentOpenAIResponse:
        """Run one structured, evidence-grounded assessment through Responses."""

        input_items: list[dict[str, object]] = []
        explicit_cache = _supports_explicit_prompt_cache(context.traceability.model_identifier)
        for item in context.input:
            rendered = item.model_dump(exclude={"section"})
            if explicit_cache and item.type == "input_file":
                rendered["prompt_cache_breakpoint"] = {"mode": "explicit"}
            input_items.append(rendered)
        arguments: dict[str, Any] = {
            "model": context.traceability.model_identifier,
            "input": [{"role": "user", "content": input_items}],
            "reasoning": {"effort": context.reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "assessment_output",
                    "strict": True,
                    "schema": context.response_schema,
                }
            },
            "prompt_cache_key": context.cache_identity.identity_hash,
        }
        if explicit_cache:
            arguments["prompt_cache_options"] = {"mode": "explicit", "ttl": "30m"}
        try:
            response = self._sdk_client.with_options(max_retries=0).responses.create(**arguments)
        except APIError as error:
            raise _translate_openai_error(error, operation="assessment") from error

        usage = response.usage
        input_details = usage.input_tokens_details if usage is not None else None
        output_details = usage.output_tokens_details if usage is not None else None
        cache_options = getattr(response, "prompt_cache_options", None)
        return AssessmentOpenAIResponse(
            response_id=response.id,
            request_id=response._request_id,
            model=getattr(response, "model", None),
            output_text=response.output_text,
            incomplete_reason=(
                response.incomplete_details.reason
                if response.incomplete_details is not None
                else None
            ),
            service_tier=response.service_tier,
            input_tokens=usage.input_tokens if usage is not None else None,
            cached_input_tokens=input_details.cached_tokens if input_details is not None else None,
            cache_write_tokens=input_details.cache_write_tokens
            if input_details is not None
            else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            reasoning_tokens=output_details.reasoning_tokens
            if output_details is not None
            else None,
            total_tokens=usage.total_tokens if usage is not None else None,
            cache_mode=cache_options.mode if cache_options is not None else None,
            cache_ttl=cache_options.ttl if cache_options is not None else None,
        )

    def upload_text(self, *, filename: str, content: bytes) -> UploadedOpenAIFile:
        """Upload one derived private Document B section for vector indexing."""

        try:
            uploaded = self._sdk_client.files.create(
                file=(filename, content, TEXT_MEDIA_TYPE),
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

    def delete_file(self, file_id: str) -> None:
        """Delete one OpenAI file, primarily for failed-operation compensation."""

        try:
            self._sdk_client.files.delete(file_id)
        except APIStatusError as error:
            if error.status_code == 404:
                return
            raise _translate_openai_error(error, operation="delete") from error
        except APIError as error:
            raise _translate_openai_error(error, operation="delete") from error

    def create_vector_store(
        self,
        *,
        name: str,
    ) -> OpenAIVectorStore:
        """Create an empty vector store for section-derived Document B sources."""

        try:
            store = self._sdk_client.vector_stores.create(
                name=name,
            )
        except APIError as error:
            raise _translate_openai_error(error, operation="vector_store_create") from error

        return OpenAIVectorStore(
            vector_store_id=store.id,
            status=store.status,
            usage_bytes=store.usage_bytes,
            request_id=store._request_id,
        )

    def attach_vector_store_file(
        self,
        *,
        vector_store_id: str,
        file_id: str,
        attributes: dict[str, str],
    ) -> None:
        """Attach one section source with filterable provenance metadata."""

        try:
            self._sdk_client.vector_stores.files.create(
                vector_store_id=vector_store_id,
                file_id=file_id,
                attributes=cast(Any, attributes),
            )
        except APIError as error:
            raise _translate_openai_error(error, operation="vector_store_attach") from error

    def wait_for_vector_store_file(
        self,
        *,
        vector_store_id: str,
        file_id: str,
        timeout_seconds: int,
    ) -> OpenAIVectorStoreFile:
        """Poll one attached file until indexing finishes or the deadline expires."""

        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                indexed_file = self._retrieve_vector_store_file(
                    vector_store_id=vector_store_id,
                    file_id=file_id,
                )
            except OpenAIClientError as error:
                if not error.retryable:
                    raise
                if time.monotonic() >= deadline:
                    raise OpenAIClientError(
                        (
                            "OpenAI did not make Document B available for indexing "
                            f"within {timeout_seconds} seconds."
                        ),
                        operation="vector_store_poll",
                        retryable=True,
                        request_id=error.request_id,
                    ) from error
                time.sleep(OPENAI_VECTOR_STORE_POLL_INTERVAL_SECONDS)
                continue
            if indexed_file.status is not OpenAIVectorStoreFileStatus.IN_PROGRESS:
                return indexed_file
            if time.monotonic() >= deadline:
                raise OpenAIClientError(
                    f"OpenAI did not finish indexing Document B within {timeout_seconds} seconds.",
                    operation="vector_store_poll",
                    retryable=True,
                    request_id=indexed_file.request_id,
                )
            time.sleep(OPENAI_VECTOR_STORE_POLL_INTERVAL_SECONDS)

    def _retrieve_vector_store_file(
        self,
        *,
        vector_store_id: str,
        file_id: str,
    ) -> OpenAIVectorStoreFile:
        try:
            indexed_file = self._sdk_client.vector_stores.files.retrieve(
                file_id,
                vector_store_id=vector_store_id,
            )
        except APIError as error:
            raise _translate_openai_error(error, operation="vector_store_poll") from error

        try:
            status = OpenAIVectorStoreFileStatus(indexed_file.status)
        except ValueError as error:
            raise OpenAIClientError(
                "OpenAI returned an unsupported vector-store file status.",
                operation="vector_store_poll",
                retryable=False,
                request_id=indexed_file._request_id,
            ) from error

        return OpenAIVectorStoreFile(
            file_id=indexed_file.id,
            vector_store_id=indexed_file.vector_store_id,
            status=status,
            usage_bytes=indexed_file.usage_bytes,
            error_code=(
                indexed_file.last_error.code if indexed_file.last_error is not None else None
            ),
            request_id=indexed_file._request_id,
        )

    def search_vector_store(
        self,
        *,
        vector_store_id: str,
        query: str,
        max_num_results: int = 1,
        filters: dict[str, object] | None = None,
    ) -> tuple[OpenAIVectorStoreSearchResult, ...]:
        """Run one direct validation search without making a model call."""

        arguments: dict[str, Any] = {
            "query": query,
            "max_num_results": max_num_results,
            "rewrite_query": False,
        }
        if filters is not None:
            arguments["filters"] = cast(Any, filters)
        try:
            page = self._sdk_client.vector_stores.search(vector_store_id, **arguments)
        except APIError as error:
            raise _translate_openai_error(error, operation="vector_store_search") from error

        return tuple(
            OpenAIVectorStoreSearchResult(
                file_id=result.file_id,
                filename=result.filename,
                score=result.score,
                text="\n".join(
                    item.text for item in result.content if item.type == "text" and item.text
                ),
                attributes=dict(getattr(result, "attributes", None) or {}),
            )
            for result in page.data
        )

    def delete_vector_store(self, vector_store_id: str) -> None:
        """Delete one vector store for compensation or explicit test cleanup."""

        try:
            self._sdk_client.vector_stores.delete(vector_store_id)
        except APIStatusError as error:
            if error.status_code == 404:
                return
            raise _translate_openai_error(error, operation="vector_store_delete") from error
        except APIError as error:
            raise _translate_openai_error(error, operation="vector_store_delete") from error

    def close(self) -> None:
        """Close HTTP resources owned by the SDK client."""

        self._sdk_client.close()


def _translate_openai_error(
    error: APIError,
    *,
    operation: str,
) -> OpenAIClientError:
    if isinstance(error, APITimeoutError):
        return OpenAIClientError(
            "The OpenAI request timed out after the configured retries.",
            operation=operation,
            retryable=True,
        )
    if isinstance(error, APIConnectionError):
        return OpenAIClientError(
            "OpenAI could not be reached after the configured retries.",
            operation=operation,
            retryable=True,
        )
    if isinstance(error, APIStatusError):
        status_code = error.status_code
        request_id = error.request_id
        retryable = (
            status_code in {408, 409, 429}
            or status_code >= 500
            or (operation == "vector_store_poll" and status_code == 404)
        )
        if status_code == 401:
            message = "OpenAI rejected the API key. Check OPENAI_API_KEY."
        elif status_code == 403:
            message = "OpenAI denied access to the requested API for this project."
        elif status_code == 429:
            message = "OpenAI rate-limited the file request after the configured retries."
        else:
            message = f"OpenAI rejected the request with HTTP status {status_code}."
        return OpenAIClientError(
            message,
            operation=operation,
            retryable=retryable,
            request_id=request_id,
        )
    return OpenAIClientError(
        "The OpenAI SDK could not complete the request.",
        operation=operation,
        retryable=False,
    )


def _supports_explicit_prompt_cache(model_identifier: str) -> bool:
    """Return whether the configured model supports explicit cache breakpoints."""

    return model_identifier.strip().lower().startswith("gpt-5.6")
