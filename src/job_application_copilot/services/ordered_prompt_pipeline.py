"""Generic durable execution for configured ordered prompt stages."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from job_application_copilot.domain import (
    BackgroundOperation,
    LlmCallStatus,
    LlmFailureCategory,
)
from job_application_copilot.llm import (
    OpenAIClientError,
    OpenAIPromptStageOperations,
    PromptStageOpenAIResponse,
    PromptStageRequest,
)
from job_application_copilot.repositories import Database, LlmCallRepository
from job_application_copilot.repositories.background_task_repository import BackgroundTaskRepository
from job_application_copilot.repositories.models import (
    BackgroundTask,
    LlmCall,
    PromptPipelineStage,
)
from job_application_copilot.repositories.prompt_pipeline_stage_repository import (
    PromptPipelineStageRepository,
)


@dataclass(frozen=True, slots=True)
class OrderedPromptStage:
    """One configured stage; its request is rebuilt from the prior durable output."""

    position: int
    pipeline_step: str
    request_factory: Callable[[str | None], PromptStageRequest]
    output_validator: Callable[[str], str] | None = None


@dataclass(frozen=True, slots=True)
class OrderedPromptPipelineResult:
    """Private outputs resulting from one complete ordered pipeline run."""

    outputs: tuple[str, ...]
    resumed_from_position: int


class OrderedPromptPipelineError(RuntimeError):
    """Raised for invalid stage configuration or an unrecoverable stage failure."""


class OrderedPromptStageFailedError(OrderedPromptPipelineError):
    """Raised after the configured retry budget for one stage is exhausted."""

    def __init__(self, pipeline_step: str) -> None:
        self.pipeline_step = pipeline_step
        super().__init__(f"Prompt pipeline stage '{pipeline_step}' failed.")


class OrderedPromptPipelineService:
    """Run configured stages sequentially without relying on provider conversation state."""

    def __init__(
        self,
        database: Database,
        client: OpenAIPromptStageOperations,
        *,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        self.database = database
        self.client = client
        self.max_retries = max_retries
        self.sleep = sleep
        self.monotonic = monotonic

    def run(
        self,
        task: BackgroundTask,
        *,
        task_attempt_id: int,
        stages: tuple[OrderedPromptStage, ...],
    ) -> OrderedPromptPipelineResult:
        """Run or manually resume a task from its first failed or missing stage."""

        self._validate_stages(stages)
        if task.operation is not BackgroundOperation.CV_GENERATION:
            raise OrderedPromptPipelineError(
                "Ordered prompt pipeline requires a CV-generation task."
            )

        outputs: list[str] = []
        resumed_from = stages[-1].position + 1
        for stage in stages:
            prior_output = outputs[-1] if outputs else None
            request = stage.request_factory(prior_output)
            self._validate_request(request)
            stored = self._stored_stage(task.id, stage.position)
            if (
                stored is not None
                and stored.status is LlmCallStatus.SUCCEEDED
                and stored.input_identity_hash == request.execution_identity_hash
                and stored.output_text is not None
            ):
                outputs.append(stored.output_text)
                continue
            if resumed_from > stages[-1].position:
                resumed_from = stage.position
            self._discard_from(task.id, stage.position)
            output = self._run_stage(
                task,
                task_attempt_id=task_attempt_id,
                stage=stage,
                request=request,
            )
            outputs.append(output)

        return OrderedPromptPipelineResult(
            outputs=tuple(outputs),
            resumed_from_position=resumed_from,
        )

    def _run_stage(
        self,
        task: BackgroundTask,
        *,
        task_attempt_id: int,
        stage: OrderedPromptStage,
        request: PromptStageRequest,
    ) -> str:
        self._set_pipeline_step(task.id, stage.pipeline_step)
        for retry_number in range(self.max_retries + 1):
            started_at = datetime.now(UTC).replace(tzinfo=None)
            started_monotonic = self.monotonic()
            try:
                response = self.client.run_prompt_stage(request)
            except OpenAIClientError as error:
                completed_at, duration = self._completed(started_at, started_monotonic)
                self._record_call(
                    task,
                    task_attempt_id,
                    stage,
                    request,
                    retry_number,
                    LlmCallStatus.FAILED,
                    started_at,
                    completed_at,
                    duration,
                    failure_category=LlmFailureCategory.PROVIDER,
                    request_id=error.request_id,
                )
                if error.retryable and retry_number < self.max_retries:
                    self.sleep(2**retry_number)
                    continue
                self._store_failure(task.id, stage, request, str(error))
                raise OrderedPromptStageFailedError(stage.pipeline_step) from error

            completed_at, duration = self._completed(started_at, started_monotonic)
            if response.incomplete_reason is not None or not response.output_text.strip():
                self._record_call(
                    task,
                    task_attempt_id,
                    stage,
                    request,
                    retry_number,
                    LlmCallStatus.FAILED,
                    started_at,
                    completed_at,
                    duration,
                    failure_category=LlmFailureCategory.INCOMPLETE_RESPONSE,
                    response=response,
                )
                if retry_number < self.max_retries:
                    self.sleep(2**retry_number)
                    continue
                self._store_failure(
                    task.id, stage, request, "The model returned no complete stage output."
                )
                raise OrderedPromptStageFailedError(stage.pipeline_step)

            try:
                output_text = (
                    stage.output_validator(response.output_text)
                    if stage.output_validator is not None
                    else response.output_text
                )
            except ValueError as error:
                self._record_call(
                    task,
                    task_attempt_id,
                    stage,
                    request,
                    retry_number,
                    LlmCallStatus.FAILED,
                    started_at,
                    completed_at,
                    duration,
                    failure_category=LlmFailureCategory.SCHEMA_VALIDATION,
                    response=response,
                )
                if retry_number < self.max_retries:
                    self.sleep(2**retry_number)
                    continue
                self._store_failure(
                    task.id, stage, request, "The model returned invalid structured stage output."
                )
                raise OrderedPromptStageFailedError(stage.pipeline_step) from error
            self._record_call(
                task,
                task_attempt_id,
                stage,
                request,
                retry_number,
                LlmCallStatus.SUCCEEDED,
                started_at,
                completed_at,
                duration,
                response=response,
            )
            with self.database.session() as session:
                PromptPipelineStageRepository(session).store_success(
                    task_id=task.id,
                    stage_position=stage.position,
                    pipeline_step=stage.pipeline_step,
                    input_identity_hash=request.execution_identity_hash,
                    output_text=output_text,
                )
            return output_text
        raise AssertionError("Prompt stage retry loop must return.")

    def _stored_stage(self, task_id: int, position: int) -> PromptPipelineStage | None:
        with self.database.session() as session:
            return PromptPipelineStageRepository(session).get(task_id, position)

    def _discard_from(self, task_id: int, position: int) -> None:
        with self.database.session() as session:
            PromptPipelineStageRepository(session).delete_from(
                task_id=task_id, stage_position=position
            )

    def _store_failure(
        self, task_id: int, stage: OrderedPromptStage, request: PromptStageRequest, message: str
    ) -> None:
        with self.database.session() as session:
            PromptPipelineStageRepository(session).store_failure(
                task_id=task_id,
                stage_position=stage.position,
                pipeline_step=stage.pipeline_step,
                input_identity_hash=request.execution_identity_hash,
                error_message=message,
            )

    def _set_pipeline_step(self, task_id: int, pipeline_step: str) -> None:
        with self.database.session() as session:
            tasks = BackgroundTaskRepository(session)
            tasks.set_pipeline_step(tasks.require(task_id), pipeline_step)

    def _record_call(
        self,
        task: BackgroundTask,
        task_attempt_id: int,
        stage: OrderedPromptStage,
        request: PromptStageRequest,
        retry_number: int,
        status: LlmCallStatus,
        started_at: datetime,
        completed_at: datetime,
        duration: float,
        *,
        failure_category: LlmFailureCategory | None = None,
        request_id: str | None = None,
        response: PromptStageOpenAIResponse | None = None,
    ) -> None:
        with self.database.session() as session:
            calls = LlmCallRepository(session)
            sequence = len(calls.list(task_id=task.id)) + 1
            calls.add(
                LlmCall(
                    job_id=task.job_id,
                    task_id=task.id,
                    task_attempt_id=task_attempt_id,
                    operation=BackgroundOperation.CV_GENERATION,
                    pipeline_step=stage.pipeline_step,
                    call_sequence=sequence,
                    requested_model=request.model_identifier,
                    resolved_model=response.model if response is not None else None,
                    status=status,
                    failure_category=failure_category,
                    retry_number=retry_number,
                    response_id=response.response_id if response is not None else None,
                    provider_request_id=(
                        response.request_id if response is not None else request_id
                    ),
                    incomplete_reason=(
                        response.incomplete_reason if response is not None else None
                    ),
                    service_tier=response.service_tier if response is not None else None,
                    input_tokens=response.input_tokens if response is not None else None,
                    cached_input_tokens=response.cached_input_tokens
                    if response is not None
                    else None,
                    cache_write_tokens=response.cache_write_tokens
                    if response is not None
                    else None,
                    output_tokens=response.output_tokens if response is not None else None,
                    reasoning_tokens=response.reasoning_tokens if response is not None else None,
                    total_tokens=response.total_tokens if response is not None else None,
                    cache_identity_hash=request.cache_identity_hash,
                    cache_identity_version=request.cache_identity_version,
                    cache_retention=response.cache_ttl if response is not None else None,
                    version_metadata={
                        "cache_explicit": response.cache_mode == "explicit" if response else False
                    },
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_seconds=duration,
                )
            )

    def _completed(self, started_at: datetime, started_monotonic: float) -> tuple[datetime, float]:
        duration = max(0.0, self.monotonic() - started_monotonic)
        return started_at + timedelta(seconds=duration), duration

    @staticmethod
    def _validate_stages(stages: tuple[OrderedPromptStage, ...]) -> None:
        if not stages:
            raise OrderedPromptPipelineError("Prompt pipeline requires at least one stage.")
        positions = [stage.position for stage in stages]
        if positions[0] < 1 or positions != list(range(positions[0], positions[0] + len(stages))):
            raise OrderedPromptPipelineError(
                "Prompt stages must have contiguous positive positions."
            )
        if any(not stage.pipeline_step.strip() for stage in stages):
            raise OrderedPromptPipelineError("Prompt stages require a pipeline step name.")

    @staticmethod
    def _validate_request(request: PromptStageRequest) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", request.execution_identity_hash) is None:
            raise OrderedPromptPipelineError(
                "Prompt stage execution identity must be a SHA-256 hash."
            )
        if re.fullmatch(r"[0-9a-f]{64}", request.cache_identity_hash) is None:
            raise OrderedPromptPipelineError("Prompt stage cache identity must be a SHA-256 hash.")
        if request.cache_identity_version < 1:
            raise OrderedPromptPipelineError(
                "Prompt stage cache identity version must be positive."
            )
