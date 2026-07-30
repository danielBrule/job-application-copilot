"""Tests for explicit pre-generation CV selection."""

from datetime import date

import pytest

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    CreateJob,
    CvSelectionStatus,
    Language,
    Location,
    Relevance,
    UserDecision,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.job_repository import JobNotFoundError
from job_application_copilot.repositories.models import Assessment
from job_application_copilot.services import CvSelectionService, CvSelectionSkipReason, JobService
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def database(tmp_path) -> Database:
    path = tmp_path / "job_application_copilot.db"
    initialize_database(path)
    database = create_database(path)
    try:
        yield database
    finally:
        database.dispose()


def test_select_jobs_marks_only_eligible_pursued_assessed_jobs(database: Database) -> None:
    jobs = JobService(database)
    selection = CvSelectionService(database)
    eligible = _add_job(jobs, user_decision=UserDecision.PURSUE)
    missing_assessment = _add_job(jobs, user_decision=UserDecision.PURSUE)
    not_pursued = _add_job(jobs, user_decision=UserDecision.UNDECIDED)
    _add_assessment(database, eligible.id, selected_cv_lane="ARCHITECTURE")
    _add_assessment(database, not_pursued.id, selected_cv_lane="ARCHITECTURE")

    result = selection.select_jobs(
        (eligible.id, missing_assessment.id, not_pursued.id, eligible.id)
    )

    assert result.selected_job_ids == (eligible.id,)
    assert tuple(skip.reason for skip in result.skipped) == (
        CvSelectionSkipReason.MISSING_ASSESSMENT,
        CvSelectionSkipReason.NOT_PURSUED,
    )
    selected_job = jobs.get(eligible.id)
    skipped_job = jobs.get(missing_assessment.id)
    assert selected_job is not None
    assert skipped_job is not None
    assert selected_job.cv_selection_status is CvSelectionStatus.SELECTED
    assert skipped_job.cv_selection_status is CvSelectionStatus.NOT_SELECTED


@pytest.mark.parametrize(
    ("assessment_status", "stale", "selected_cv_lane", "expected_reason"),
    [
        (AssessmentStatus.PENDING, False, None, CvSelectionSkipReason.ASSESSMENT_NOT_READY),
        (AssessmentStatus.FAILED, False, None, CvSelectionSkipReason.ASSESSMENT_NOT_READY),
        (AssessmentStatus.ASSESSED, True, "ARCHITECTURE", CvSelectionSkipReason.ASSESSMENT_STALE),
        (AssessmentStatus.ASSESSED, False, None, CvSelectionSkipReason.MISSING_CV_LANE),
    ],
)
def test_select_jobs_reports_each_assessment_eligibility_failure(
    database: Database,
    assessment_status: AssessmentStatus,
    stale: bool,
    selected_cv_lane: str | None,
    expected_reason: CvSelectionSkipReason,
) -> None:
    jobs = JobService(database)
    job = _add_job(jobs, user_decision=UserDecision.PURSUE)
    _add_assessment(
        database,
        job.id,
        status=assessment_status,
        selected_cv_lane=selected_cv_lane,
        stale=stale,
    )

    result = CvSelectionService(database).select_jobs((job.id,))

    assert result.selected_job_ids == ()
    assert result.skipped[0].reason is expected_reason


def test_select_jobs_reports_already_selected_and_missing_jobs(database: Database) -> None:
    jobs = JobService(database)
    job = _add_job(jobs, user_decision=UserDecision.PURSUE)
    _add_assessment(database, job.id, selected_cv_lane="ARCHITECTURE")
    selection = CvSelectionService(database)

    assert selection.select_jobs((job.id,)).selected_job_ids == (job.id,)
    repeated = selection.select_jobs((job.id,))

    assert repeated.skipped[0].reason is CvSelectionSkipReason.ALREADY_SELECTED
    with pytest.raises(JobNotFoundError, match="Job 999"):
        selection.select_jobs((job.id, 999))
    selected_job = jobs.get(job.id)
    assert selected_job is not None
    assert selected_job.cv_selection_status is CvSelectionStatus.SELECTED


def _add_job(jobs: JobService, *, user_decision: UserDecision):
    return jobs.create(
        CreateJob(
            company="Example Ltd",
            job_title="Platform Architect",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Lead architecture work.",
            date_added=date(2026, 7, 30),
            user_decision=user_decision,
        )
    )


def _add_assessment(
    database: Database,
    job_id: int,
    *,
    status: AssessmentStatus = AssessmentStatus.ASSESSED,
    selected_cv_lane: str | None = None,
    stale: bool = False,
) -> None:
    job = JobService(database).get(job_id)
    assert job is not None
    with database.session() as session:
        if status is AssessmentStatus.ASSESSED:
            assessment = Assessment(
                job_id=job_id,
                status=status,
                model_relevance=Relevance.HIGH,
                role_snapshot="Role snapshot",
                real_mandate="Real mandate",
                primary_role_family="ARCHITECTURE",
                seniority_fit=8,
                technical_bar="Technical bar",
                fit_score=8,
                priority_score=8,
                decision=AssessmentDecision.GO,
                decision_reason="Strong fit.",
                recommended_document_b_lane="ARCHITECTURE",
                selected_cv_lane=selected_cv_lane,
                assessed_at=job.assessment_input_updated_at,
                source_job_updated_at=(
                    job.assessment_input_updated_at.replace(year=2025)
                    if stale
                    else job.assessment_input_updated_at
                ),
            )
        elif status is AssessmentStatus.FAILED:
            assessment = Assessment(job_id=job_id, status=status, error_message="Timed out.")
        else:
            assessment = Assessment(job_id=job_id, status=status)
        session.add(assessment)
