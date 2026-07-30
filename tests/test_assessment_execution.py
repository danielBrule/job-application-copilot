"""Focused execution and telemetry tests for one OpenAI assessment."""

import json
from datetime import date
from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import Language, LlmCallStatus, Location
from job_application_copilot.llm import AssessmentOpenAIResponse
from job_application_copilot.repositories import Database, LlmCallRepository, create_database
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import (
    AssessmentCacheIdentity,
    AssessmentContext,
    AssessmentTextInput,
)
from job_application_copilot.services.assessment_context import AssessmentTraceability
from job_application_copilot.services.assessment_execution import AssessmentExecutionService
from job_application_copilot.services.database_bootstrap import initialize_database

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "assessment_output_valid.json"
LANES = ("FICTIONAL_ARCHITECTURE_LEAD", "FICTIONAL_AI_DEPLOYMENT_LEAD")


class StaticContextBuilder:
    def __init__(self, context: AssessmentContext) -> None:
        self.context = context

    def build(self, job_id: int) -> AssessmentContext:
        return self.context


class FakeClient:
    def __init__(self, responses: list[AssessmentOpenAIResponse]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    def assess(self, context: AssessmentContext) -> AssessmentOpenAIResponse:
        self.calls += 1
        return next(self.responses)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    path = tmp_path / "assessment.db"
    initialize_database(path)
    database = create_database(path)
    try:
        yield database
    finally:
        database.dispose()


def add_job(database: Database) -> int:
    with database.session() as session:
        job = Job(
            company="Example",
            job_title="Architecture Lead",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Lead architecture.",
            date_added=date(2026, 7, 30),
        )
        session.add(job)
        session.flush()
        return job.id


def context() -> AssessmentContext:
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


def response(output_text: str) -> AssessmentOpenAIResponse:
    return AssessmentOpenAIResponse(
        response_id="resp_test",
        request_id="req_test",
        model="gpt-5.6-sol",
        output_text=output_text,
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


def test_validates_assessment_and_persists_usage(database: Database, tmp_path: Path) -> None:
    job_id = add_job(database)
    client = FakeClient([response(FIXTURE_PATH.read_text(encoding="utf-8"))])
    service = AssessmentExecutionService(
        database,
        AppSettings(_env_file=None),
        client,
        context_builder=StaticContextBuilder(context()),
        monotonic=iter((0.0, 1.25)).__next__,
    )

    result = service.assess(job_id)

    assert result.succeeded
    assert result.output is not None
    with database.session() as session:
        call = LlmCallRepository(session).list(job_id=job_id)[0]
    assert call.status is LlmCallStatus.SUCCEEDED
    assert call.cached_input_tokens == 80
    assert call.cache_retention == "30m"
    assert call.version_metadata["cache_explicit"] is True


def test_retries_schema_failure_and_retains_each_attempt(database: Database) -> None:
    job_id = add_job(database)
    valid = FIXTURE_PATH.read_text(encoding="utf-8")
    client = FakeClient([response(json.dumps({"model_relevance": "HIGH"})), response(valid)])
    service = AssessmentExecutionService(
        database,
        AppSettings(_env_file=None, assessment_retry_base_delay_seconds=0),
        client,
        context_builder=StaticContextBuilder(context()),
        monotonic=iter((0.0, 1.0, 2.0, 3.0)).__next__,
    )

    result = service.assess(job_id)

    assert result.succeeded
    assert client.calls == 2
    with database.session() as session:
        calls = LlmCallRepository(session).list(job_id=job_id)
    assert [call.status for call in calls] == [LlmCallStatus.FAILED, LlmCallStatus.SUCCEEDED]
