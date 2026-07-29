"""Repository tests for current assessment lifecycle and staleness."""

from datetime import date, datetime
from pathlib import Path

import pytest

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    Language,
    Location,
    Relevance,
)
from job_application_copilot.repositories import (
    AssessmentNotAllowedError,
    AssessmentNotFoundError,
    AssessmentRepository,
    Database,
    create_database,
)
from job_application_copilot.repositories.models import Assessment, Job
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


def add_job(database: Database) -> Job:
    with database.session() as session:
        job = Job(
            company="Example",
            job_title="Platform Director",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Lead the platform organisation.",
            date_added=date(2026, 7, 29),
        )
        session.add(job)
        session.flush()
        return job


def test_add_get_require_and_missing(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with migrated_database.session() as session:
        repository = AssessmentRepository(session)
        added = repository.add(Assessment(job_id=job.id))
        assessment_id = added.id
        assert repository.get_for_job(job.id) is added
        assert repository.require_for_job(job.id) is added

    with migrated_database.session() as session:
        stored = AssessmentRepository(session).get_for_job(job.id)
        assert stored is not None
        assert stored.id == assessment_id
        with pytest.raises(AssessmentNotFoundError, match="Job 999"):
            AssessmentRepository(session).require_for_job(999)


def test_initial_failure_can_retry_but_success_cannot_be_marked_running_or_failed(
    migrated_database: Database,
) -> None:
    job = add_job(migrated_database)
    with migrated_database.session() as session:
        repository = AssessmentRepository(session)
        assessment = repository.add(Assessment(job_id=job.id))
        repository.mark_running(assessment)
        repository.mark_failed(assessment, "Timed out")
        repository.mark_running(assessment)
        assessment.status = AssessmentStatus.ASSESSED
        assessment.model_relevance = Relevance.HIGH
        assessment.role_snapshot = "Role snapshot"
        assessment.real_mandate = "Real mandate"
        assessment.primary_role_family = "Primary"
        assessment.secondary_role_family = "Secondary"
        assessment.fit_score = 8
        assessment.priority_score = 7
        assessment.technical_bar = "Technical bar"
        assessment.seniority_fit = 9
        assessment.decision = AssessmentDecision.GO
        assessment.decision_reason = "Strong fit"
        assessment.recommended_document_b_lane = "HEAD_OF_SOLUTIONS_ARCHITECTURE"
        assessment.assessed_at = datetime(2026, 7, 29, 10, 0, 0)
        assessment.source_job_updated_at = job.assessment_input_updated_at
        session.flush()

        with pytest.raises(AssessmentNotAllowedError, match="remains available"):
            repository.mark_running(assessment)
        with pytest.raises(AssessmentNotAllowedError, match="must not replace"):
            repository.mark_failed(assessment, "Reassessment failed")


def test_stale_compares_only_assessment_input_timestamp(
    migrated_database: Database,
) -> None:
    job = add_job(migrated_database)
    source_timestamp = job.assessment_input_updated_at
    with migrated_database.session() as session:
        repository = AssessmentRepository(session)
        assessment = repository.add(
            Assessment(
                job_id=job.id,
                status=AssessmentStatus.ASSESSED,
                model_relevance=Relevance.HIGH,
                role_snapshot="Role snapshot",
                real_mandate="Real mandate",
                primary_role_family="Primary",
                secondary_role_family="Secondary",
                fit_score=8,
                priority_score=7,
                technical_bar="Technical bar",
                seniority_fit=9,
                decision=AssessmentDecision.GO,
                decision_reason="Strong fit",
                recommended_document_b_lane="HEAD_OF_SOLUTIONS_ARCHITECTURE",
                assessed_at=datetime(2026, 7, 29, 10, 0, 0),
                source_job_updated_at=source_timestamp,
            )
        )
        stored_job = session.get(Job, job.id)
        assert stored_job is not None
        assert repository.is_stale(assessment, stored_job) is False

        stored_job.assessment_input_updated_at = datetime(2026, 7, 29, 10, 0, 1)
        assert repository.is_stale(assessment, stored_job) is True
