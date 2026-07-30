"""Constraint tests for current structured assessments."""

from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    Language,
    Location,
    Relevance,
)
from job_application_copilot.repositories import Database, create_database
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


def completed_assessment(job: Job, **overrides: object) -> Assessment:
    values: dict[str, object] = {
        "job_id": job.id,
        "status": AssessmentStatus.ASSESSED,
        "model_relevance": Relevance.HIGH,
        "role_snapshot": "Lead a distributed platform group.",
        "real_mandate": "Stabilise delivery and modernise the platform.",
        "primary_role_family": "Technology leadership",
        "secondary_role_family": "Solutions architecture",
        "seniority_fit": 9,
        "technical_bar": "Strong architecture depth is required.",
        "tech_bar_fit": 8,
        "fit_score": 9,
        "priority_score": 8,
        "decision": AssessmentDecision.GO,
        "decision_reason": "Strong evidence-backed alignment.",
        "interview_probability_low": 6,
        "interview_probability_high": 8,
        "interview_probability_confidence": 7,
        "strong_fit_signals": ["Led platform transformation"],
        "red_flags": ["Broad operational remit"],
        "sustainability_risks": ["High travel expectation"],
        "evidence_gaps": ["No sector-specific experience"],
        "evidence_anchors": [{"id": "A-17", "claim": "Platform leadership"}],
        "evidence_confidence": 8,
        "recommended_document_b_lane": "HEAD_OF_SOLUTIONS_ARCHITECTURE",
        "selected_cv_lane": "HEAD_OF_SOLUTIONS_ARCHITECTURE",
        "secondary_cv_angle": "Transformation leadership",
        "overclaiming_risks": ["Do not claim sole ownership"],
        "document_a_version": 3,
        "prompt_version": 2,
        "model_name": "gpt-test-2026-07-01",
        "assessed_at": datetime(2026, 7, 29, 10, 0, 0),
        "source_job_updated_at": job.assessment_input_updated_at,
    }
    values.update(overrides)
    return Assessment(**values)


def test_persists_complete_structured_assessment(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with migrated_database.session() as session:
        assessment = completed_assessment(job)
        session.add(assessment)
        session.flush()
        assessment_id = assessment.id

    with migrated_database.session() as session:
        stored = session.get(Assessment, assessment_id)

    assert stored is not None
    assert stored.model_relevance is Relevance.HIGH
    assert stored.fit_score == 9
    assert stored.priority_score == 8
    assert stored.evidence_anchors == [{"id": "A-17", "claim": "Platform leadership"}]
    assert stored.document_a_version == 3
    assert stored.model_name == "gpt-test-2026-07-01"


def test_persists_completed_assessment_without_secondary_role_family(
    migrated_database: Database,
) -> None:
    job = add_job(migrated_database)
    with migrated_database.session() as session:
        session.add(completed_assessment(job, secondary_role_family=None))
        session.flush()


def test_rejects_blank_secondary_role_family(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with pytest.raises(IntegrityError, match="secondary_role_family_not_blank"):
        with migrated_database.session() as session:
            session.add(completed_assessment(job, secondary_role_family=" "))
            session.flush()


def test_persists_failed_initial_assessment(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with migrated_database.session() as session:
        session.add(
            Assessment(
                job_id=job.id,
                status=AssessmentStatus.FAILED,
                error_message="Provider request timed out.",
            )
        )
        session.flush()


def test_allows_only_one_current_assessment_per_job(migrated_database: Database) -> None:
    job = add_job(migrated_database)
    with pytest.raises(IntegrityError, match="assessments.job_id"):
        with migrated_database.session() as session:
            session.add_all(
                [
                    Assessment(job_id=job.id),
                    Assessment(job_id=job.id),
                ]
            )
            session.flush()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"fit_score": 11}, "fit_score_range"),
        ({"priority_score": -1}, "priority_score_range"),
        ({"seniority_fit": -1}, "seniority_fit_range"),
        ({"tech_bar_fit": 12}, "tech_bar_fit_range"),
        ({"evidence_confidence": 20}, "evidence_confidence_range"),
        (
            {"interview_probability_low": 8, "interview_probability_high": 3},
            "interview_probability_order",
        ),
        ({"status": AssessmentStatus.FAILED}, "error_matches_status"),
    ],
)
def test_rejects_invalid_scores_and_failure_state(
    migrated_database: Database,
    overrides: dict[str, object],
    constraint: str,
) -> None:
    job = add_job(migrated_database)
    with pytest.raises(IntegrityError, match=constraint):
        with migrated_database.session() as session:
            session.add(completed_assessment(job, **overrides))
            session.flush()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_relevance", None),
        ("role_snapshot", None),
        ("real_mandate", " "),
        ("primary_role_family", None),
        ("fit_score", None),
        ("priority_score", None),
        ("technical_bar", None),
        ("seniority_fit", None),
        ("decision", None),
        ("decision_reason", None),
        ("recommended_document_b_lane", None),
    ],
)
def test_assessed_result_requires_every_requested_scalar_field(
    migrated_database: Database,
    field: str,
    value: object,
) -> None:
    job = add_job(migrated_database)
    with pytest.raises(IntegrityError, match="assessed_fields_complete"):
        with migrated_database.session() as session:
            session.add(completed_assessment(job, **{field: value}))
            session.flush()
