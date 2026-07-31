"""Tests for Jobs dashboard row shaping and stable selection."""

from datetime import date, datetime

import pytest

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    CvSelectionStatus,
    Language,
    Location,
    UserDecision,
)
from job_application_copilot.repositories.models import Job
from job_application_copilot.services.job_service import JobAssessmentSummary
from job_application_copilot.ui.components.jobs_dashboard import (
    TABLE_COLUMN_ORDER,
    JobDashboardRow,
    selected_job_ids,
    shape_job_rows,
)


def make_job(job_id: int, company: str) -> Job:
    return Job(
        id=job_id,
        company=company,
        job_title="Platform Engineer",
        job_url=f"https://example.com/jobs/{job_id}",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Build reliable systems.",
        date_added=date(2026, 7, 24),
        created_at=datetime(2026, 7, 24, 10, 0, 0),
        updated_at=datetime(2026, 7, 24, 12, 30, 45),
    )


def test_shape_job_rows_preserves_order_and_core_values() -> None:
    rows = shape_job_rows([make_job(2, "Second"), make_job(1, "First")])

    assert [row.job_id for row in rows] == [2, 1]
    assert rows[0] == JobDashboardRow(
        job_id=2,
        company="Second",
        job_title="Platform Engineer",
        job_url="https://example.com/jobs/2",
        location="UK",
        language="EN",
        source="LinkedIn",
        date_added=date(2026, 7, 24),
        updated_at=datetime(2026, 7, 24, 12, 30, 45),
        assessment_status="Not assessed",
        recommendation=None,
        fit_score=None,
        interview_probability_low=None,
        interview_probability_high=None,
        user_decision="Undecided",
        selected_cv_lane=None,
        cv_selection_status="Not selected",
        application_status=None,
        next_action=None,
    )
    assert tuple(rows[0].display_record()) == TABLE_COLUMN_ORDER
    assert "job_id" not in rows[0].display_record()


def test_shape_job_rows_displays_current_assessment_values_and_staleness() -> None:
    summary = JobAssessmentSummary(
        status=AssessmentStatus.ASSESSED,
        decision=AssessmentDecision.GO.value,
        fit_score=8,
        interview_probability_low=4,
        interview_probability_high=6,
        selected_cv_lane="ARCHITECTURE",
    )
    job = make_job(2, "Second")
    job.user_decision = UserDecision.PURSUE
    job.cv_selection_status = CvSelectionStatus.SELECTED
    job.application_status = "Applied"
    job.next_action = "Follow up"
    (row,) = shape_job_rows([job], {2: summary})

    assert row.display_record()["assessment_status"] == "Assessed"
    assert row.display_record()["recommendation"] == "GO"
    assert row.display_record()["fit_score"] == 8
    assert row.display_record()["interview_probability"] == "5 / 10"
    assert row.display_record()["user_decision"] == "Pursue"
    assert row.display_record()["selected_cv_lane"] == "ARCHITECTURE"
    assert row.display_record()["cv_selection_status"] == "Selected for CV generation"
    assert row.display_record()["cv_status"] == "Not available yet"
    assert row.display_record()["open_cv"] == "Unavailable"
    assert row.display_record()["application_status"] == "Applied"
    assert row.display_record()["next_action"] == "Follow up"


def test_selected_positions_map_to_stable_job_ids() -> None:
    rows = shape_job_rows(
        [
            make_job(30, "Third"),
            make_job(20, "Second"),
            make_job(10, "First"),
        ]
    )

    assert selected_job_ids(rows, [2, 0]) == (10, 30)
    assert selected_job_ids(rows, []) == ()


@pytest.mark.parametrize("position", [-1, 2])
def test_invalid_selected_position_is_rejected(position: int) -> None:
    rows = shape_job_rows([make_job(10, "First"), make_job(20, "Second")])

    with pytest.raises(ValueError, match="outside the jobs table"):
        selected_job_ids(rows, [position])
