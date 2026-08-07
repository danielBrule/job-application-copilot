"""Tests for global Jobs dashboard usage and processing KPIs."""

from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    BackgroundOperation,
    CvSource,
    CvStatus,
    Language,
    LlmCallStatus,
    LlmFailureCategory,
    Location,
)
from job_application_copilot.repositories import Database, LlmCallRepository, create_database
from job_application_copilot.repositories.models import Cv, Job, LlmCall
from job_application_copilot.services.dashboard_kpis import DashboardKpiService
from job_application_copilot.services.database_bootstrap import initialize_database


def test_usage_uses_all_reported_calls_for_totals_and_successful_calls_for_averages(
    tmp_path: Path,
) -> None:
    database = _migrated_database(tmp_path)
    try:
        with database.session() as session:
            first_job = _add_job(session, "First")
            second_job = _add_job(session, "Second")
            calls = LlmCallRepository(session)
            calls.add(_make_call(first_job.id, total_tokens=120, duration_seconds=1.5))
            calls.add(
                _make_call(
                    second_job.id,
                    call_sequence=2,
                    status=LlmCallStatus.FAILED,
                    failure_category=LlmFailureCategory.TIMEOUT,
                    total_tokens=60,
                    duration_seconds=0.75,
                )
            )
            calls.add(
                _make_call(
                    first_job.id,
                    operation=BackgroundOperation.CV_GENERATION,
                    pipeline_step="ENGLISH_STAGE_1",
                    call_sequence=3,
                    total_tokens=500,
                    duration_seconds=4.0,
                )
            )

        kpis = DashboardKpiService(database).usage()

        assert kpis.assessment.total_tokens == 180
        assert kpis.assessment.average_tokens_per_successful_call == 120
        assert kpis.assessment.total_duration_seconds == 2.25
        assert kpis.assessment.average_duration_seconds_per_successful_call == 1.5
        assert kpis.cv_generation.total_tokens == 500
        assert kpis.cv_generation.average_tokens_per_successful_call == 500
        assert kpis.cv_generation.total_duration_seconds == 4.0
        assert kpis.cv_generation.average_duration_seconds_per_successful_call == 4.0
    finally:
        database.dispose()


def test_usage_returns_zero_totals_and_no_averages_without_successful_calls(tmp_path: Path) -> None:
    database = _migrated_database(tmp_path)
    try:
        with database.session() as session:
            job = _add_job(session, "Failed")
            LlmCallRepository(session).add(
                _make_call(
                    job.id,
                    status=LlmCallStatus.FAILED,
                    failure_category=LlmFailureCategory.TIMEOUT,
                    response_id=None,
                    total_tokens=None,
                    duration_seconds=0.25,
                )
            )

        kpis = DashboardKpiService(database).usage()

        assert kpis.assessment.total_tokens == 0
        assert kpis.assessment.average_tokens_per_successful_call is None
        assert kpis.assessment.total_duration_seconds == 0.25
        assert kpis.assessment.average_duration_seconds_per_successful_call is None
        assert kpis.cv_generation.total_tokens == 0
        assert kpis.cv_generation.average_tokens_per_successful_call is None
        assert kpis.cv_generation.total_duration_seconds == 0.0
        assert kpis.cv_generation.average_duration_seconds_per_successful_call is None
    finally:
        database.dispose()


def test_workflow_counts_jobs_cvs_by_source_and_approved_cvs(tmp_path: Path) -> None:
    database = _migrated_database(tmp_path)
    try:
        with database.session() as session:
            generated_job = _add_job(session, "Generated")
            uploaded_job = _add_job(session, "Uploaded")
            unapproved_job = _add_job(session, "Unapproved")
            session.add_all(
                [
                    _make_cv(generated_job.id, CvSource.GENERATED, CvStatus.APPROVED),
                    _make_cv(uploaded_job.id, CvSource.UPLOADED, CvStatus.READY_FOR_REVIEW),
                    _make_cv(unapproved_job.id, CvSource.GENERATED, CvStatus.READY_FOR_REVIEW),
                ]
            )

        kpis = DashboardKpiService(database).workflow()

        assert kpis.jobs_entered == 3
        assert kpis.cvs_generated == 2
        assert kpis.cvs_uploaded == 1
        assert kpis.cvs_approved == 1
    finally:
        database.dispose()


def _migrated_database(tmp_path: Path) -> Database:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    return create_database(database_path)


def _add_job(session: Session, company: str) -> Job:
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


def _make_call(job_id: int, **overrides: object) -> LlmCall:
    values: dict[str, object] = {
        "job_id": job_id,
        "operation": BackgroundOperation.ASSESSMENT,
        "pipeline_step": "ASSESSMENT",
        "call_sequence": 1,
        "provider": "OPENAI",
        "requested_model": "gpt-test",
        "status": LlmCallStatus.SUCCEEDED,
        "retry_number": 0,
        "response_id": "resp_test",
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "version_metadata": {},
        "started_at": datetime(2026, 7, 29, 10, 0, 0),
        "completed_at": datetime(2026, 7, 29, 10, 0, 2),
        "duration_seconds": 1.5,
    }
    values.update(overrides)
    return LlmCall(**values)


def _make_cv(job_id: int, source: CvSource, status: CvStatus) -> Cv:
    return Cv(
        job_id=job_id,
        source=source,
        status=status,
        language=Language.EN,
        file_name=f"{job_id}.docx",
        file_path=f"C:/private/cvs/{job_id}.docx",
        approved_at=datetime(2026, 7, 29, 12, 0, 0) if status is CvStatus.APPROVED else None,
    )
