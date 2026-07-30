"""Tests for Jobs dashboard row shaping and stable selection."""

from datetime import date, datetime

import pytest

from job_application_copilot.domain import Language, Location
from job_application_copilot.repositories.models import Job
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
        assessment_stale=False,
    )
    assert tuple(rows[0].display_record()) == TABLE_COLUMN_ORDER
    assert "job_id" not in rows[0].display_record()


def test_shape_job_rows_displays_stale_assessment_state() -> None:
    (row,) = shape_job_rows([make_job(2, "Second")], {2: True})

    assert row.assessment_stale is True
    assert row.display_record()["assessment_stale"] == "Yes"


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
