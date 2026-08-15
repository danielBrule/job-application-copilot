"""Integration tests for durable ordered prompt-pipeline execution."""

from datetime import date
from pathlib import Path

import pytest

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundTaskStatus,
    Language,
    Location,
)
from job_application_copilot.llm import (
    OpenAIClientError,
    PromptStageInput,
    PromptStageOpenAIResponse,
    PromptStageRequest,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.background_task_repository import (
    BackgroundBatchRepository,
    BackgroundTaskRepository,
)
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask, Job
from job_application_copilot.repositories.prompt_pipeline_stage_repository import (
    PromptPipelineStageRepository,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.ordered_prompt_pipeline import (
    OrderedPromptPipelineService,
    OrderedPromptStage,
    OrderedPromptStageFailedError,
)

IDENTITY = "a" * 64


class FakeClient:
    def __init__(self, results: list[PromptStageOpenAIResponse | OpenAIClientError]) -> None:
        self.results = iter(results)
        self.prior_outputs: list[str | None] = []
        self.requests: list[PromptStageRequest] = []

    def run_prompt_stage(self, request: PromptStageRequest) -> PromptStageOpenAIResponse:
        self.requests.append(request)
        self.prior_outputs.append(
            next((item.text for item in request.input if item.section == "prior"), None)
        )
        result = next(self.results)
        if isinstance(result, OpenAIClientError):
            raise result
        return result


@pytest.fixture
def database(tmp_path: Path) -> Database:
    path = tmp_path / "pipeline.db"
    initialize_database(path)
    database = create_database(path)
    try:
        yield database
    finally:
        database.dispose()


def response(text: str) -> PromptStageOpenAIResponse:
    return PromptStageOpenAIResponse(
        response_id=f"resp_{text}",
        request_id="req_1",
        model="gpt-5.6-sol",
        output_text=text,
        incomplete_reason=None,
        service_tier="default",
        input_tokens=20,
        cached_input_tokens=10,
        cache_write_tokens=10,
        output_tokens=5,
        reasoning_tokens=1,
        total_tokens=25,
        cache_mode="explicit",
        cache_ttl="30m",
    )


def claimed_task(database: Database) -> tuple[BackgroundTask, int]:
    with database.session() as session:
        job = Job(
            company="Example",
            job_title="Lead",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Description",
            date_added=date(2026, 8, 6),
        )
        session.add(job)
        session.flush()
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.CV_GENERATION)
        )
        task = BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=batch.id, job_id=job.id, operation=BackgroundOperation.CV_GENERATION
            )
        )
        task = BackgroundTaskRepository(session).transition(task, BackgroundTaskStatus.RUNNING)
        attempt = BackgroundTaskRepository(session).get_running_attempt(task.id)
        assert attempt is not None
        return task, attempt.id


def stages() -> tuple[OrderedPromptStage, ...]:
    def build(position: int):
        def factory(prior: str | None) -> PromptStageRequest:
            items = [PromptStageInput(section="instruction", text=f"stage {position}")]
            if prior is not None:
                items.append(PromptStageInput(section="prior", text=prior))
            return PromptStageRequest(
                model_identifier="gpt-5.6-sol",
                input=tuple(items),
                cache_identity_hash=IDENTITY,
                cache_identity_version=1,
                execution_identity_hash=(str(position) * 64),
            )

        return factory

    return tuple(
        OrderedPromptStage(
            position=index,
            pipeline_step=f"CV_GENERATION_STAGE_{index}",
            request_factory=build(index),
        )
        for index in range(1, 4)
    )


def test_runs_three_stages_in_order_and_persists_outputs(database: Database) -> None:
    task, attempt_id = claimed_task(database)
    client = FakeClient([response("brief"), response("draft"), response("final")])

    result = OrderedPromptPipelineService(database, client, max_retries=0).run(
        task, task_attempt_id=attempt_id, stages=stages()
    )

    assert result.outputs == ("brief", "draft", "final")
    assert client.prior_outputs == [None, "brief", "draft"]
    with database.session() as session:
        stored = PromptPipelineStageRepository(session).list_for_task(task.id)
    assert [item.output_text for item in stored] == ["brief", "draft", "final"]


def test_allows_a_single_later_stage_to_keep_its_configured_position(database: Database) -> None:
    task, attempt_id = claimed_task(database)
    stage = OrderedPromptStage(
        position=2,
        pipeline_step="CV_GENERATION_STAGE_2_DRAFT",
        request_factory=stages()[1].request_factory,
    )

    result = OrderedPromptPipelineService(
        database, FakeClient([response("draft")]), max_retries=0
    ).run(task, task_attempt_id=attempt_id, stages=(stage,))

    assert result.outputs == ("draft",)
    assert result.resumed_from_position == 2


def test_validation_retry_adds_safe_correction_without_raw_error_text(database: Database) -> None:
    task, attempt_id = claimed_task(database)
    client = FakeClient([response("bad"), response("final")])
    stage = OrderedPromptStage(
        position=1,
        pipeline_step="CV_GENERATION_STAGE_3_FINAL",
        request_factory=stages()[0].request_factory,
        output_validator=lambda text: (
            text
            if text == "final"
            else (_ for _ in ()).throw(
                ValueError("must not contain a structured-output serialization fragment")
            )
        ),
    )

    result = OrderedPromptPipelineService(database, client, max_retries=1, sleep=lambda _: None).run(
        task, task_attempt_id=attempt_id, stages=(stage,)
    )

    assert result.outputs == ("final",)
    assert len(client.requests) == 2
    correction = client.requests[1].input[-1]
    assert correction.section == "validation_correction"
    assert "serialization fragments" in correction.text
    assert "must not contain" not in correction.text


def test_placeholder_validation_retry_requires_unique_slots() -> None:
    request = stages()[0].request_factory(None)

    corrected = OrderedPromptPipelineService._correction_request(
        request, ValueError("each generated value must have a unique DOCX placeholder")
    )

    correction = corrected.input[-1]
    assert correction.section == "validation_correction"
    assert "exactly once" in correction.text
    assert "do not reuse" in correction.text


def test_manual_retry_resumes_from_failed_stage(database: Database) -> None:
    task, first_attempt_id = claimed_task(database)
    first_client = FakeClient(
        [
            response("brief"),
            OpenAIClientError("safe failure", operation="prompt_stage", retryable=False),
        ]
    )
    service = OrderedPromptPipelineService(database, first_client, max_retries=0)

    with pytest.raises(OrderedPromptStageFailedError, match="CV_GENERATION_STAGE_2"):
        service.run(task, task_attempt_id=first_attempt_id, stages=stages())

    with database.session() as session:
        tasks = BackgroundTaskRepository(session)
        stored_task = tasks.require(task.id)
        tasks.transition(stored_task, BackgroundTaskStatus.FAILED, error_message="failed")
        tasks.transition(stored_task, BackgroundTaskStatus.PENDING)
        retried_task = tasks.claim_next_pending((BackgroundOperation.CV_GENERATION,))
        assert retried_task is not None
        retry_attempt = tasks.get_running_attempt(task.id)
        assert retry_attempt is not None

    retry_client = FakeClient([response("draft"), response("final")])
    result = OrderedPromptPipelineService(database, retry_client, max_retries=0).run(
        retried_task, task_attempt_id=retry_attempt.id, stages=stages()
    )

    assert result.resumed_from_position == 2
    assert result.outputs == ("brief", "draft", "final")
    assert retry_client.prior_outputs == ["brief", "draft"]
