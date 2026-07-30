"""Execute and validate one OpenAI assessment without assessment-row persistence."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    AssessmentOutput,
    BackgroundOperation,
    LlmCallStatus,
    LlmFailureCategory,
)
from job_application_copilot.llm import (
    AssessmentOpenAIResponse,
    OpenAIAssessmentOperations,
    OpenAIClientError,
)
from job_application_copilot.repositories import Database, LlmCallRepository
from job_application_copilot.repositories.models import LlmCall
from job_application_copilot.services.assessment_context import (
    AssessmentContext,
    AssessmentContextBuilder,
)


@dataclass(frozen=True, slots=True)
class AssessmentExecutionResult:
    """Validated output or a safe terminal failure for one job assessment."""

    job_id: int
    context: AssessmentContext
    output: AssessmentOutput | None
    error_message: str | None
    failure_category: LlmFailureCategory | None
    attempts: int
    model_name: str | None = None
    retryable: bool = False

    @property
    def succeeded(self) -> bool:
        return self.output is not None


class AssessmentExecutionService:
    """Own explicit assessment retries and record every provider invocation."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        client: OpenAIAssessmentOperations,
        *,
        context_builder: AssessmentContextBuilder | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client
        self.context_builder = context_builder or AssessmentContextBuilder(database, settings)
        self.sleep = sleep
        self.monotonic = monotonic

    def assess(
        self,
        job_id: int,
        *,
        task_id: int | None = None,
        task_attempt_id: int | None = None,
    ) -> AssessmentExecutionResult:
        """Build the authoritative context and execute it within the retry budget."""

        context = self.context_builder.build(job_id)
        for retry_number in range(self.settings.assessment_max_retries + 1):
            result = self._attempt(
                job_id,
                context,
                retry_number,
                task_id=task_id,
                task_attempt_id=task_attempt_id,
            )
            if (
                result.succeeded
                or not result.retryable
                or retry_number == self.settings.assessment_max_retries
            ):
                return result
            if result.failure_category not in {
                LlmFailureCategory.TIMEOUT,
                LlmFailureCategory.RATE_LIMIT,
                LlmFailureCategory.NETWORK,
                LlmFailureCategory.PROVIDER,
                LlmFailureCategory.INCOMPLETE_RESPONSE,
                LlmFailureCategory.SCHEMA_VALIDATION,
            }:
                return result
            delay = self.settings.assessment_retry_base_delay_seconds * (2**retry_number)
            if delay:
                self.sleep(delay)
        raise AssertionError("Assessment retry loop must return.")

    def _attempt(
        self,
        job_id: int,
        context: AssessmentContext,
        retry_number: int,
        *,
        task_id: int | None,
        task_attempt_id: int | None,
    ) -> AssessmentExecutionResult:
        started_at = datetime.now(UTC).replace(tzinfo=None)
        started_monotonic = self.monotonic()
        try:
            response = self.client.assess(context)
        except OpenAIClientError as error:
            completed_at, duration = self._completed(started_at, started_monotonic)
            category = _provider_failure_category(error)
            self._record_failure(
                job_id,
                context,
                retry_number,
                category,
                started_at,
                completed_at,
                duration,
                task_id=task_id,
                task_attempt_id=task_attempt_id,
                request_id=error.request_id,
            )
            return AssessmentExecutionResult(
                job_id,
                context,
                None,
                str(error),
                category,
                retry_number + 1,
                retryable=error.retryable,
            )

        completed_at, duration = self._completed(started_at, started_monotonic)
        if response.incomplete_reason is not None or not response.output_text.strip():
            self._record_failure(
                job_id,
                context,
                retry_number,
                LlmFailureCategory.INCOMPLETE_RESPONSE,
                started_at,
                completed_at,
                duration,
                task_id=task_id,
                task_attempt_id=task_attempt_id,
                response=response,
            )
            return AssessmentExecutionResult(
                job_id,
                context,
                None,
                "OpenAI returned an incomplete assessment response.",
                LlmFailureCategory.INCOMPLETE_RESPONSE,
                retry_number + 1,
                response.model,
                retryable=True,
            )
        try:
            output = AssessmentOutput.model_validate_json(
                response.output_text,
                context={"allowed_lane_ids": _allowed_lane_ids(context)},
            )
        except ValidationError:
            self._record_failure(
                job_id,
                context,
                retry_number,
                LlmFailureCategory.SCHEMA_VALIDATION,
                started_at,
                completed_at,
                duration,
                task_id=task_id,
                task_attempt_id=task_attempt_id,
                response=response,
            )
            return AssessmentExecutionResult(
                job_id,
                context,
                None,
                "OpenAI returned an assessment that did not match the required structure.",
                LlmFailureCategory.SCHEMA_VALIDATION,
                retry_number + 1,
                response.model,
                retryable=True,
            )
        self._record_success(
            job_id,
            context,
            retry_number,
            started_at,
            completed_at,
            duration,
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            response=response,
        )
        return AssessmentExecutionResult(
            job_id,
            context,
            output,
            None,
            None,
            retry_number + 1,
            response.model,
        )

    def _completed(self, started_at: datetime, started_monotonic: float) -> tuple[datetime, float]:
        duration = max(0.0, self.monotonic() - started_monotonic)
        return started_at + timedelta(seconds=duration), duration

    def _record_success(
        self,
        job_id: int,
        context: AssessmentContext,
        retry_number: int,
        started_at: datetime,
        completed_at: datetime,
        duration: float,
        response: AssessmentOpenAIResponse,
        *,
        task_id: int | None,
        task_attempt_id: int | None,
    ) -> None:
        self._record(
            job_id,
            context,
            retry_number,
            LlmCallStatus.SUCCEEDED,
            None,
            started_at,
            completed_at,
            duration,
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            response=response,
        )

    def _record_failure(
        self,
        job_id: int,
        context: AssessmentContext,
        retry_number: int,
        category: LlmFailureCategory,
        started_at: datetime,
        completed_at: datetime,
        duration: float,
        *,
        task_id: int | None,
        task_attempt_id: int | None,
        response: AssessmentOpenAIResponse | None = None,
        request_id: str | None = None,
    ) -> None:
        self._record(
            job_id,
            context,
            retry_number,
            LlmCallStatus.FAILED,
            category,
            started_at,
            completed_at,
            duration,
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            response=response,
            request_id=request_id,
        )

    def _record(
        self,
        job_id: int,
        context: AssessmentContext,
        retry_number: int,
        status: LlmCallStatus,
        category: LlmFailureCategory | None,
        started_at: datetime,
        completed_at: datetime,
        duration: float,
        *,
        task_id: int | None,
        task_attempt_id: int | None,
        response: AssessmentOpenAIResponse | None = None,
        request_id: str | None = None,
    ) -> None:
        values = _call_values(context)
        if response is not None:
            values.update(
                response_id=response.response_id,
                provider_request_id=response.request_id,
                resolved_model=response.model,
                incomplete_reason=response.incomplete_reason,
                service_tier=response.service_tier,
                input_tokens=response.input_tokens,
                cached_input_tokens=response.cached_input_tokens,
                cache_write_tokens=response.cache_write_tokens,
                output_tokens=response.output_tokens,
                reasoning_tokens=response.reasoning_tokens,
                total_tokens=response.total_tokens,
                cache_retention=response.cache_ttl,
            )
            version_metadata = values["version_metadata"]
            assert isinstance(version_metadata, dict)
            version_metadata["cache_explicit"] = response.cache_mode == "explicit"
        else:
            values["provider_request_id"] = request_id
        call = LlmCall(
            job_id=job_id,
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            call_sequence=retry_number + 1,
            retry_number=retry_number,
            status=status,
            failure_category=category,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            **values,
        )
        with self.database.session() as session:
            LlmCallRepository(session).add(call)


def _allowed_lane_ids(context: AssessmentContext) -> tuple[str, ...]:
    values = context.response_schema["properties"]["primary_role_family"]["enum"]
    return tuple(str(value) for value in values)


def _call_values(context: AssessmentContext) -> dict[str, object]:
    trace = context.traceability
    return {
        "operation": BackgroundOperation.ASSESSMENT,
        "pipeline_step": "ASSESSMENT",
        "provider": "OPENAI",
        "requested_model": trace.model_identifier,
        "resolved_model": None,
        "response_id": None,
        "provider_request_id": None,
        "http_status_code": None,
        "incomplete_reason": None,
        "service_tier": None,
        "input_tokens": None,
        "cached_input_tokens": None,
        "cache_write_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
        "cache_identity_hash": context.cache_identity.identity_hash,
        "cache_identity_version": context.cache_identity.identity_version,
        "cache_retention": None,
        "version_metadata": {
            "document_a_version": trace.document_a_version,
            "prompt_version": trace.prompt_version,
            "schema_version": trace.schema_version,
            "routing_set_id": trace.routing_set_id,
            "routing_config_version": trace.routing_config_version,
            "reasoning_effort": trace.reasoning_effort,
        },
    }


def _provider_failure_category(error: OpenAIClientError) -> LlmFailureCategory:
    if error.operation == "assessment" and error.retryable:
        return LlmFailureCategory.PROVIDER
    return LlmFailureCategory.PROVIDER if not error.retryable else LlmFailureCategory.NETWORK
