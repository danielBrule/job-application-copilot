"""Tests for global Jobs dashboard usage and processing KPIs."""

from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    BackgroundOperation,
    CvSelectionStatus,
    CvSource,
    CvStatus,
    Language,
    LlmCallStatus,
    LlmFailureCategory,
    Location,
    Relevance,
    UserDecision,
)
from job_application_copilot.repositories import Database, LlmCallRepository, create_database
from job_application_copilot.repositories.models import Assessment, Cv, Job, LlmCall
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


def test_workflow_counts_jobs_assessments_and_applications(tmp_path: Path) -> None:
    database = _migrated_database(tmp_path)
    try:
        with database.session() as session:
            awaiting_review_job = _add_job(session, "Awaiting review")
            reviewed_job = _add_job(session, "Reviewed")
            applied_job = _add_job(session, "Applied")
            selected_without_cv = _add_job(session, "Selected without CV")
            selected_with_cv = _add_job(session, "Selected with CV")
            reviewed_job.user_decision = UserDecision.PURSUE
            applied_job.application_status = "Applied"
            selected_without_cv.cv_selection_status = CvSelectionStatus.SELECTED
            selected_with_cv.cv_selection_status = CvSelectionStatus.SELECTED
            session.add_all(
                [
                    _make_assessed_assessment(awaiting_review_job),
                    _make_assessed_assessment(reviewed_job),
                    _make_assessed_assessment(selected_without_cv),
                    _make_assessed_assessment(selected_with_cv),
                    _make_generated_cv(selected_with_cv.id, CvStatus.READY_FOR_REVIEW),
                ]
            )

        kpis = DashboardKpiService(database).workflow()

        assert kpis.jobs_entered == 5
        assert kpis.assessed_jobs == 4
        assert kpis.applied_jobs == 1
        assert kpis.unassessed_jobs == 1
        assert kpis.selected_jobs_without_generated_cv == 1
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


def _make_assessed_assessment(job: Job) -> Assessment:
    return Assessment(
        job_id=job.id,
        status=AssessmentStatus.ASSESSED,
        model_relevance=Relevance.HIGH,
        role_snapshot="Platform leadership role.",
        real_mandate="Improve delivery.",
        primary_role_family="ARCHITECTURE",
        seniority_fit=8,
        technical_bar="Strong architecture judgement.",
        fit_score=8,
        priority_score=7,
        decision=AssessmentDecision.GO,
        decision_reason="Evidence supports the mandate.",
        recommended_document_b_lane="ARCHITECTURE",
        assessed_at=job.assessment_input_updated_at,
        source_job_updated_at=job.assessment_input_updated_at,
    )


def _make_generated_cv(job_id: int, status: CvStatus) -> Cv:
    return Cv(
        job_id=job_id,
        source=CvSource.GENERATED,
        status=status,
        language=Language.EN,
        file_name="generated-cv.docx",
        file_path="/private/generated-cv.docx",
        approved_at=(datetime(2026, 7, 29, 10, 0, 0) if status == CvStatus.APPROVED else None),
    )
