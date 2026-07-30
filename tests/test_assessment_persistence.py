"""Integration tests for persisting the current assessment result."""

import json
from datetime import date
from pathlib import Path

import pytest

from job_application_copilot.domain import (
    AssessmentOutput,
    AssessmentStatus,
    Language,
    LlmFailureCategory,
    Location,
    Relevance,
)
from job_application_copilot.repositories import AssessmentRepository, Database, create_database
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import (
    AssessmentCacheIdentity,
    AssessmentContext,
    AssessmentExecutionResult,
    AssessmentPersistenceService,
    AssessmentTextInput,
)
from job_application_copilot.services.assessment_context import AssessmentTraceability
from job_application_copilot.services.database_bootstrap import initialize_database

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "assessment_output_valid.json"
LANES = ("FICTIONAL_ARCHITECTURE_LEAD", "FICTIONAL_AI_DEPLOYMENT_LEAD")


@pytest.fixture
def database(tmp_path: Path) -> Database:
    path = tmp_path / "assessment-persistence.db"
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


def context(*, document_a_version: int = 1) -> AssessmentContext:
    schema = {"properties": {"primary_role_family": {"enum": list(LANES)}}}
    traceability = AssessmentTraceability(
        document_a_reference_asset_id=document_a_version,
        document_a_version=document_a_version,
        document_a_hash=f"sha256:document-a-{document_a_version}",
        prompt_asset_key="assessment",
        prompt_version=2,
        prompt_hash="sha256:prompt",
        schema_version=1,
        schema_hash="sha256:schema",
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
            document_a_version=document_a_version,
            document_a_hash=f"sha256:document-a-{document_a_version}",
            prompt_asset_key="assessment",
            prompt_version=2,
            prompt_hash="sha256:prompt",
            schema_version=1,
            schema_hash="sha256:schema",
        ),
    )


def output(*, relevance: Relevance = Relevance.HIGH) -> AssessmentOutput:
    values = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    values["model_relevance"] = relevance.value
    return AssessmentOutput.model_validate(values, context={"allowed_lane_ids": LANES})


def succeeded_result(
    job_id: int,
    *,
    assessment_output: AssessmentOutput | None = None,
    document_a_version: int = 1,
) -> AssessmentExecutionResult:
    return AssessmentExecutionResult(
        job_id=job_id,
        context=context(document_a_version=document_a_version),
        output=assessment_output or output(),
        error_message=None,
        failure_category=None,
        attempts=1,
        model_name="gpt-5.6-sol-2026-07-30",
    )


def failed_result(
    job_id: int, message: str = "Assessment request timed out."
) -> AssessmentExecutionResult:
    return AssessmentExecutionResult(
        job_id=job_id,
        context=context(),
        output=None,
        error_message=message,
        failure_category=LlmFailureCategory.TIMEOUT,
        attempts=3,
    )


def test_success_creates_complete_current_assessment(database: Database) -> None:
    job_id = add_job(database)

    stored = AssessmentPersistenceService(database).persist(succeeded_result(job_id))

    assert stored.status is AssessmentStatus.ASSESSED
    assert stored.model_relevance is Relevance.HIGH
    assert stored.document_a_version == 1
    assert stored.prompt_version == 2
    assert stored.model_name == "gpt-5.6-sol-2026-07-30"
    assert stored.assessed_at is not None
    assert stored.source_job_updated_at is not None
    assert stored.error_message is None
    with database.session() as session:
        assessment = AssessmentRepository(session).require_for_job(job_id)
        job = session.get(Job, job_id)
        assert job is not None
        assert assessment.source_job_updated_at == job.assessment_input_updated_at
        assert assessment.evidence_anchors[0]["source_reference"] == "A-FICTIONAL-01"


def test_failure_creates_retryable_initial_assessment(database: Database) -> None:
    job_id = add_job(database)

    stored = AssessmentPersistenceService(database).persist(failed_result(job_id))

    assert stored.status is AssessmentStatus.FAILED
    assert stored.error_message == "Assessment request timed out."
    assert stored.assessed_at is None


def test_successful_reassessment_replaces_model_fields_and_keeps_user_fields(
    database: Database,
) -> None:
    job_id = add_job(database)
    service = AssessmentPersistenceService(database)
    first = service.persist(succeeded_result(job_id))
    first_assessed_at = first.assessed_at
    with database.session() as session:
        assessment = AssessmentRepository(session).require_for_job(job_id)
        assessment.selected_cv_lane = "FICTIONAL_AI_DEPLOYMENT_LEAD"
        assessment.assessment_notes = "User note"

    replacement = service.persist(
        succeeded_result(
            job_id,
            assessment_output=output(relevance=Relevance.LOW),
            document_a_version=2,
        )
    )

    assert replacement.id == first.id
    assert replacement.model_relevance is Relevance.LOW
    assert replacement.document_a_version == 2
    assert replacement.assessed_at is not None
    assert replacement.assessed_at >= first_assessed_at
    assert replacement.selected_cv_lane == "FICTIONAL_AI_DEPLOYMENT_LEAD"
    assert replacement.assessment_notes == "User note"


def test_failed_reassessment_keeps_prior_success_unchanged(database: Database) -> None:
    job_id = add_job(database)
    service = AssessmentPersistenceService(database)
    prior = service.persist(succeeded_result(job_id))
    prior_values = (
        prior.id,
        prior.model_relevance,
        prior.document_a_version,
        prior.assessed_at,
        prior.error_message,
    )

    returned = service.persist(failed_result(job_id, "Provider unavailable."))

    assert (
        returned.id,
        returned.model_relevance,
        returned.document_a_version,
        returned.assessed_at,
        returned.error_message,
    ) == prior_values
    with database.session() as session:
        stored = AssessmentRepository(session).require_for_job(job_id)
        assert stored.status is AssessmentStatus.ASSESSED
        assert stored.error_message is None


def test_document_a_version_does_not_automatically_mark_assessment_stale(
    database: Database,
) -> None:
    job_id = add_job(database)
    service = AssessmentPersistenceService(database)
    service.persist(succeeded_result(job_id, document_a_version=1))

    with database.session() as session:
        assessment = AssessmentRepository(session).require_for_job(job_id)
        job = session.get(Job, job_id)
        assert job is not None
        assert AssessmentRepository(session).is_stale(assessment, job) is False
