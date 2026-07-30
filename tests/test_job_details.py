"""Tests for Job Details input handling and assessment view state."""

from datetime import date

import pytest

from job_application_copilot.domain import AssessmentStatus, Language, Location, Relevance
from job_application_copilot.repositories import AssessmentRepository, create_database
from job_application_copilot.repositories.models import Assessment, Job
from job_application_copilot.services import JobService
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.ui.components.job_details import (
    _effective_relevance,
    parse_job_id,
)


@pytest.mark.parametrize("value", [None, "", "abc", "1.5", "0", "-1"])
def test_parse_job_id_rejects_missing_or_invalid_values(value: str | None) -> None:
    with pytest.raises(ValueError):
        parse_job_id(value)


def test_parse_job_id_accepts_positive_integer() -> None:
    assert parse_job_id("42") == 42


def test_assessment_detail_returns_current_result_and_detects_staleness(tmp_path) -> None:
    database_path = tmp_path / "assessment-detail.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        with database.session() as session:
            job = Job(
                company="Example Ltd",
                job_title="Architecture Lead",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_description="Lead architecture.",
                date_added=date(2026, 7, 30),
            )
            session.add(job)
            session.flush()
            assessment = Assessment(
                job_id=job.id,
                status=AssessmentStatus.ASSESSED,
                model_relevance=Relevance.HIGH,
                role_snapshot="Lead architecture.",
                real_mandate="Improve delivery.",
                primary_role_family="ARCHITECTURE",
                seniority_fit=8,
                technical_bar="Architecture judgement.",
                tech_bar_fit=7,
                fit_score=8,
                priority_score=7,
                decision="GO",
                decision_reason="Strong evidence.",
                interview_probability_low=5,
                interview_probability_high=7,
                interview_probability_confidence=6,
                recommended_document_b_lane="ARCHITECTURE",
                document_a_version=1,
                prompt_version=2,
                model_name="test-model",
                assessed_at=job.assessment_input_updated_at,
                source_job_updated_at=job.assessment_input_updated_at,
            )
            AssessmentRepository(session).add(assessment)

        service = JobService(database)
        current = service.assessment_detail(job.id)
        assert current.assessment is not None
        assert current.is_stale is False
        assert _effective_relevance(current) == "High"

        with database.session() as session:
            stored_job = session.get(Job, job.id)
            assert stored_job is not None
            stored_job.assessment_input_updated_at = stored_job.assessment_input_updated_at.replace(
                year=2027
            )

        stale = service.assessment_detail(job.id)
        assert stale.is_stale is True
    finally:
        database.dispose()
