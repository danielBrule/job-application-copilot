"""Worker integration tests for durable assessment-task handling."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    AssessmentStatus,
    BackgroundOperation,
    BackgroundTaskStatus,
    Language,
    Location,
)
from job_application_copilot.llm import AssessmentOpenAIResponse, OpenAIClientError
from job_application_copilot.repositories import (
    AssessmentRepository,
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    LlmCallRepository,
    create_database,
)
from job_application_copilot.repositories.models import (
    BackgroundBatch,
    BackgroundTask,
    BackgroundTaskAttempt,
    Job,
)
from job_application_copilot.services import (
    AssessmentCacheIdentity,
    AssessmentContext,
    AssessmentTextInput,
)
from job_application_copilot.services.assessment_context import AssessmentTraceability
from job_application_copilot.services.assessment_worker_handler import AssessmentWorkerHandler
from job_application_copilot.services.background_worker import BackgroundWorker
from job_application_copilot.services.database_bootstrap import initialize_database

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "assessment_output_valid.json"
LANES = ("FICTIONAL_ARCHITECTURE_LEAD", "FICTIONAL_AI_DEPLOYMENT_LEAD")


class StaticContextBuilder:
    def build(self, job_id: int) -> AssessmentContext:
        del job_id
        return assessment_context()


class FakeClient:
    def __init__(self, outcomes: list[AssessmentOpenAIResponse | Exception]) -> None:
        self.outcomes = iter(outcomes)
        self.close_count = 0

    def assess(self, context: AssessmentContext) -> AssessmentOpenAIResponse:
        del context
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        self.close_count += 1


@pytest.fixture
def database(tmp_path: Path) -> Database:
    path = tmp_path / "assessment-worker.db"
    initialize_database(path)
    database = create_database(path)
    try:
        yield database
    finally:
        database.dispose()


def add_tasks(database: Database, companies: list[str]) -> list[BackgroundTask]:
    with database.session() as session:
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        )
        tasks: list[BackgroundTask] = []
        for company in companies:
            job = Job(
                company=company,
                job_title="Architecture Lead",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_description="Lead architecture.",
                date_added=date(2026, 7, 30),
            )
            session.add(job)
            session.flush()
            tasks.append(
                BackgroundTaskRepository(session).add(
                    BackgroundTask(
                        batch_id=batch.id,
                        job_id=job.id,
                        operation=BackgroundOperation.ASSESSMENT,
                    )
                )
            )
        return tasks


def assessment_context() -> AssessmentContext:
    schema = {"properties": {"primary_role_family": {"enum": list(LANES)}}}
    traceability = AssessmentTraceability(
        document_a_reference_asset_id=1,
        document_a_version=1,
        document_a_hash="sha256:a",
        prompt_asset_key="assessment",
        prompt_version=1,
        prompt_hash="sha256:b",
        schema_version=1,
        schema_hash="sha256:c",
        model_identifier="gpt-5.6-sol",
        reasoning_effort="medium",
        routing_set_id=1,
        routing_config_version="v1",
    )
    return AssessmentContext(
        input=(AssessmentTextInput(section="assessment_instructions", text="Assess safely."),),
        stable_prefix_item_count=1,
        reasoning_effort="medium",
        response_schema=schema,
        traceability=traceability,
        cache_identity=AssessmentCacheIdentity(
            identity_version=1,
            identity_hash="a" * 64,
            operation="ASSESSMENT",
            pipeline_step="ASSESSMENT",
            model_identifier="gpt-5.6-sol",
            document_a_version=1,
            document_a_hash="sha256:a",
            prompt_asset_key="assessment",
            prompt_version=1,
            prompt_hash="sha256:b",
            schema_version=1,
            schema_hash="sha256:c",
        ),
    )


def response() -> AssessmentOpenAIResponse:
    return AssessmentOpenAIResponse(
        response_id="resp_test",
        request_id="req_test",
        model="gpt-5.6-sol",
        output_text=FIXTURE_PATH.read_text(encoding="utf-8"),
        incomplete_reason=None,
        service_tier="default",
        input_tokens=100,
        cached_input_tokens=80,
        cache_write_tokens=20,
        output_tokens=30,
        reasoning_tokens=10,
        total_tokens=130,
        cache_mode="explicit",
        cache_ttl="30m",
    )


def worker(database: Database, client: FakeClient) -> BackgroundWorker:
    settings = AppSettings(_env_file=None, assessment_max_retries=0)
    handler = AssessmentWorkerHandler(
        database,
        settings,
        client_factory=lambda _: client,
        context_builder=StaticContextBuilder(),
    )
    return BackgroundWorker(database, {BackgroundOperation.ASSESSMENT: handler})


def test_assessment_tasks_complete_independently_and_link_usage_to_attempts(
    database: Database,
) -> None:
    successful, failed = add_tasks(database, ["Success", "Failure"])
    client = FakeClient(
        [
            response(),
            OpenAIClientError(
                "OpenAI could not be reached.",
                operation="assessment",
                retryable=False,
            ),
        ]
    )
    task_worker = worker(database, client)

    assert task_worker.process_next_task()
    assert task_worker.process_next_task()
    assert not task_worker.process_next_task()

    with database.session() as session:
        tasks = BackgroundTaskRepository(session)
        stored_success = tasks.require(successful.id)
        stored_failure = tasks.require(failed.id)
        assert stored_success.status is BackgroundTaskStatus.COMPLETED
        assert stored_success.pipeline_step == "ASSESSMENT"
        assert stored_failure.status is BackgroundTaskStatus.FAILED
        assert stored_failure.error_message == "Task handler failed; see the private worker log."
        assert (
            AssessmentRepository(session).require_for_job(successful.job_id).status
            is AssessmentStatus.ASSESSED
        )
        failed_assessment = AssessmentRepository(session).require_for_job(failed.job_id)
        assert failed_assessment.status is AssessmentStatus.FAILED
        assert failed_assessment.error_message == "OpenAI could not be reached."

        calls = LlmCallRepository(session).list(job_id=successful.job_id)
        assert len(calls) == 1
        attempt = session.scalar(
            select(BackgroundTaskAttempt).where(BackgroundTaskAttempt.task_id == successful.id)
        )
        assert attempt is not None
        assert calls[0].task_id == successful.id
        assert calls[0].task_attempt_id == attempt.id
    assert client.close_count == 2


def test_failed_reassessment_keeps_the_prior_successful_assessment(database: Database) -> None:
    (first_task,) = add_tasks(database, ["Example"])
    client = FakeClient(
        [
            response(),
            OpenAIClientError(
                "OpenAI could not be reached.",
                operation="assessment",
                retryable=False,
            ),
        ]
    )
    task_worker = worker(database, client)
    assert task_worker.process_next_task()

    with database.session() as session:
        first_assessment = AssessmentRepository(session).require_for_job(first_task.job_id)
        original_assessed_at = first_assessment.assessed_at
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        )
        retry_task = BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=first_task.job_id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )

    assert task_worker.process_next_task()

    with database.session() as session:
        assessment = AssessmentRepository(session).require_for_job(first_task.job_id)
        assert assessment.status is AssessmentStatus.ASSESSED
        assert assessment.assessed_at == original_assessed_at
        assert assessment.error_message is None
        assert (
            BackgroundTaskRepository(session).require(retry_task.id).status
            is BackgroundTaskStatus.FAILED
        )
