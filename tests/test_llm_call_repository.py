"""Repository and aggregation tests for LLM-call telemetry."""

from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundTaskStatus,
    Language,
    LlmCallStatus,
    LlmFailureCategory,
    Location,
)
from job_application_copilot.repositories import (
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    LlmCallAssociationError,
    LlmCallRepository,
    create_database,
)
from job_application_copilot.repositories.models import (
    BackgroundBatch,
    BackgroundTask,
    BackgroundTaskAttempt,
    Job,
    LlmCall,
)
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def migrated_database(tmp_path: Path) -> Database:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database
    finally:
        database.dispose()


def add_job(session: Session, company: str = "Example") -> Job:
    job = Job(
        company=company,
        job_title="Platform Engineer",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Build reliable systems.",
        date_added=date(2026, 7, 29),
    )
    session.add(job)
    session.flush()
    return job


def make_call(job_id: int, **overrides: object) -> LlmCall:
    values: dict[str, object] = {
        "job_id": job_id,
        "operation": BackgroundOperation.ASSESSMENT,
        "pipeline_step": "ASSESSMENT",
        "call_sequence": 1,
        "provider": "OPENAI",
        "requested_model": "gpt-test",
        "resolved_model": "gpt-test-2026-07-01",
        "status": LlmCallStatus.SUCCEEDED,
        "retry_number": 0,
        "response_id": "resp_test",
        "provider_request_id": "req_test",
        "service_tier": "default",
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "cache_write_tokens": 10,
        "output_tokens": 20,
        "reasoning_tokens": 5,
        "total_tokens": 120,
        "cache_identity_hash": "a" * 64,
        "cache_identity_version": 1,
        "cache_retention": "24h",
        "version_metadata": {
            "prompt_key": "assessment",
            "prompt_version": 3,
            "document_a_hash": "b" * 64,
        },
        "started_at": datetime(2026, 7, 29, 10, 0, 0),
        "completed_at": datetime(2026, 7, 29, 10, 0, 2),
        "duration_seconds": 1.5,
    }
    values.update(overrides)
    return LlmCall(**values)


def test_records_and_lists_call_for_exact_background_attempt(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        job = add_job(session)
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        )
        task = BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=job.id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )
        BackgroundTaskRepository(session).transition(task, BackgroundTaskStatus.RUNNING)
        attempt = session.scalar(
            select(BackgroundTaskAttempt).where(BackgroundTaskAttempt.task_id == task.id)
        )
        assert attempt is not None
        call = LlmCallRepository(session).add(
            make_call(job.id, task_id=task.id, task_attempt_id=attempt.id)
        )
        call_id = call.id

    with migrated_database.session() as session:
        stored = LlmCallRepository(session).list(job_id=job.id)

    assert [item.id for item in stored] == [call_id]
    assert stored[0].task_id == task.id
    assert stored[0].task_attempt_id == attempt.id


def test_rejects_mismatched_job_task_operation_and_attempt(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        first_job = add_job(session, "First")
        second_job = add_job(session, "Second")
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        )
        task = BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=first_job.id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )
        BackgroundTaskRepository(session).transition(task, BackgroundTaskStatus.RUNNING)

        with pytest.raises(LlmCallAssociationError, match="jobs differ"):
            LlmCallRepository(session).add(make_call(second_job.id, task_id=task.id))

        with pytest.raises(LlmCallAssociationError, match="operations differ"):
            LlmCallRepository(session).add(
                make_call(
                    first_job.id,
                    task_id=task.id,
                    operation=BackgroundOperation.CV_GENERATION,
                )
            )

        with pytest.raises(LlmCallAssociationError, match="must also identify"):
            LlmCallRepository(session).add(make_call(first_job.id, task_attempt_id=1))


def test_aggregates_reported_usage_including_failed_calls(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        job = add_job(session)
        other_job = add_job(session, "Other")
        calls = LlmCallRepository(session)
        calls.add(make_call(job.id, call_sequence=1))
        calls.add(
            make_call(
                job.id,
                call_sequence=2,
                status=LlmCallStatus.FAILED,
                failure_category=LlmFailureCategory.SCHEMA_VALIDATION,
                input_tokens=50,
                cached_input_tokens=20,
                cache_write_tokens=None,
                output_tokens=10,
                reasoning_tokens=2,
                total_tokens=60,
                duration_seconds=0.75,
            )
        )
        calls.add(
            make_call(
                job.id,
                operation=BackgroundOperation.CV_GENERATION,
                pipeline_step="ENGLISH_STAGE_1",
                call_sequence=1,
                input_tokens=500,
                total_tokens=520,
            )
        )
        calls.add(make_call(other_job.id))

    with migrated_database.session() as session:
        totals = LlmCallRepository(session).aggregate(
            job_id=job.id,
            operation=BackgroundOperation.ASSESSMENT,
        )

    assert totals.call_count == 2
    assert totals.succeeded_count == 1
    assert totals.failed_count == 1
    assert totals.calls_with_usage == 2
    assert totals.input_tokens == 150
    assert totals.cached_input_tokens == 60
    assert totals.cache_write_tokens == 10
    assert totals.output_tokens == 30
    assert totals.reasoning_tokens == 7
    assert totals.total_tokens == 180
    assert totals.duration_seconds == pytest.approx(2.25)
    assert totals.successful_total_tokens == 120
    assert totals.successful_duration_seconds == pytest.approx(1.5)


def test_aggregation_distinguishes_no_usage_from_zero_totals(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        job = add_job(session)
        LlmCallRepository(session).add(
            make_call(
                job.id,
                status=LlmCallStatus.FAILED,
                failure_category=LlmFailureCategory.TIMEOUT,
                response_id=None,
                resolved_model=None,
                input_tokens=None,
                cached_input_tokens=None,
                cache_write_tokens=None,
                output_tokens=None,
                reasoning_tokens=None,
                total_tokens=None,
            )
        )

    with migrated_database.session() as session:
        totals = LlmCallRepository(session).aggregate(job_id=job.id)

    assert totals.call_count == 1
    assert totals.failed_count == 1
    assert totals.calls_with_usage == 0
    assert totals.total_tokens == 0
    assert totals.successful_total_tokens == 0
    assert totals.successful_duration_seconds == 0


def test_aggregates_global_dashboard_usage_by_operation(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        first_job = add_job(session)
        second_job = add_job(session, "Other")
        calls = LlmCallRepository(session)
        calls.add(make_call(first_job.id, total_tokens=100, duration_seconds=1.0))
        calls.add(
            make_call(
                second_job.id,
                call_sequence=2,
                status=LlmCallStatus.FAILED,
                failure_category=LlmFailureCategory.TIMEOUT,
                total_tokens=40,
                duration_seconds=0.5,
            )
        )
        calls.add(
            make_call(
                first_job.id,
                operation=BackgroundOperation.CV_GENERATION,
                pipeline_step="ENGLISH_STAGE_1",
                call_sequence=3,
                total_tokens=500,
                duration_seconds=4.0,
            )
        )

    with migrated_database.session() as session:
        totals = LlmCallRepository(session).aggregate_dashboard()

    assessment = totals[BackgroundOperation.ASSESSMENT]
    assert assessment.call_count == 2
    assert assessment.total_tokens == 140
    assert assessment.duration_seconds == pytest.approx(1.5)
    assert assessment.successful_total_tokens == 100
    assert assessment.successful_duration_seconds == pytest.approx(1.0)
    cv_generation = totals[BackgroundOperation.CV_GENERATION]
    assert cv_generation.call_count == 1
    assert cv_generation.total_tokens == 500
    assert cv_generation.successful_total_tokens == 500


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cache_identity_hash": "not-a-hash"}, "lowercase SHA-256"),
        ({"version_metadata": {"prompt": {"raw": "content"}}}, "scalar identifiers"),
    ],
)
def test_rejects_unsafe_or_ambiguous_trace_metadata(
    migrated_database: Database,
    overrides: dict[str, object],
    message: str,
) -> None:
    with migrated_database.session() as session:
        job = add_job(session)
        with pytest.raises(LlmCallAssociationError, match=message):
            LlmCallRepository(session).add(make_call(job.id, **overrides))
