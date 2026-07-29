"""Constraint tests for privacy-safe LLM-call persistence."""

from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from job_application_copilot.domain import (
    BackgroundOperation,
    Language,
    LlmCallStatus,
    LlmFailureCategory,
    Location,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import Job, LlmCall
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


def add_job(database: Database) -> int:
    with database.session() as session:
        job = Job(
            company="Example",
            job_title="Platform Engineer",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Build reliable systems.",
            date_added=date(2026, 7, 29),
        )
        session.add(job)
        session.flush()
        return job.id


def successful_call(job_id: int, **overrides: object) -> LlmCall:
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
        "input_tokens": 100,
        "cached_input_tokens": 80,
        "cache_write_tokens": 0,
        "output_tokens": 20,
        "reasoning_tokens": 5,
        "total_tokens": 120,
        "started_at": datetime(2026, 7, 29, 10, 0, 0),
        "completed_at": datetime(2026, 7, 29, 10, 0, 2),
        "duration_seconds": 1.75,
    }
    values.update(overrides)
    return LlmCall(**values)


def test_persists_zero_cache_write_separately_from_unreported_value(
    migrated_database: Database,
) -> None:
    job_id = add_job(migrated_database)
    with migrated_database.session() as session:
        reported_zero = successful_call(job_id, call_sequence=1, cache_write_tokens=0)
        unreported = successful_call(job_id, call_sequence=2, cache_write_tokens=None)
        session.add_all([reported_zero, unreported])
        session.flush()
        reported_zero_id = reported_zero.id
        unreported_id = unreported.id

    with migrated_database.session() as session:
        assert session.get(LlmCall, reported_zero_id).cache_write_tokens == 0  # type: ignore[union-attr]
        assert session.get(LlmCall, unreported_id).cache_write_tokens is None  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"input_tokens": -1}, "input_tokens_non_negative"),
        ({"cached_input_tokens": 101}, "cached_not_above_input"),
        ({"call_sequence": 0}, "call_sequence_positive"),
        ({"duration_seconds": -0.1}, "duration_non_negative"),
        (
            {"completed_at": datetime(2026, 7, 29, 9, 59, 59)},
            "timestamp_order",
        ),
    ],
)
def test_rejects_invalid_usage_and_timing(
    migrated_database: Database,
    overrides: dict[str, object],
    constraint: str,
) -> None:
    job_id = add_job(migrated_database)

    with pytest.raises(IntegrityError, match=constraint):
        with migrated_database.session() as session:
            session.add(successful_call(job_id, **overrides))
            session.flush()


def test_requires_failure_category_only_for_failed_calls(
    migrated_database: Database,
) -> None:
    job_id = add_job(migrated_database)
    failed = successful_call(
        job_id,
        status=LlmCallStatus.FAILED,
        failure_category=LlmFailureCategory.TIMEOUT,
        response_id=None,
        input_tokens=None,
        cached_input_tokens=None,
        cache_write_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
        total_tokens=None,
    )

    with migrated_database.session() as session:
        session.add(failed)
        session.flush()

    with pytest.raises(IntegrityError, match="failure_category_matches_status"):
        with migrated_database.session() as session:
            session.add(
                successful_call(
                    job_id,
                    call_sequence=2,
                    status=LlmCallStatus.FAILED,
                    failure_category=None,
                )
            )
            session.flush()


def test_rejects_success_without_response_or_core_usage(
    migrated_database: Database,
) -> None:
    job_id = add_job(migrated_database)

    with pytest.raises(IntegrityError, match="success_has_core_usage"):
        with migrated_database.session() as session:
            session.add(successful_call(job_id, response_id=None, total_tokens=None))
            session.flush()
