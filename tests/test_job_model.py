"""Integration tests for the Job persistence model and migration."""

from datetime import date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from job_application_copilot.domain import Language, Location, UserDecision
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import Job
from job_application_copilot.services.database_bootstrap import (
    MIGRATIONS_DIRECTORY,
    initialize_database,
)

FOUNDATION_REVISION = "0001_database_foundation"
JOB_REVISION = "0002_create_jobs_table"


@pytest.fixture
def migrated_database(tmp_path: Path) -> Database:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database
    finally:
        database.dispose()


def test_creates_job_with_internal_defaults(migrated_database: Database) -> None:
    job = Job(
        company="Example Ltd",
        job_title="Platform Engineer",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Build and operate the platform.",
        date_added=date.today(),
    )

    with migrated_database.session() as session:
        session.add(job)
        session.flush()

    assert job.id is not None
    assert job.location is Location.UK
    assert job.language is Language.EN
    assert job.source == "LinkedIn"
    assert job.date_added == date.today()
    assert job.user_decision is UserDecision.UNDECIDED
    assert job.created_at.microsecond == 0
    assert job.updated_at.microsecond == 0
    assert job.created_at == job.updated_at


def test_direct_insert_uses_internal_database_defaults(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        job_id = session.scalar(
            text(
                """
                INSERT INTO jobs (
                    company,
                    job_title,
                    location,
                    language,
                    source,
                    job_description,
                    date_added
                )
                VALUES (
                    'Example Ltd',
                    'Engineer',
                    'UK',
                    'EN',
                    'LinkedIn',
                    'Build systems.',
                    '2026-07-24'
                )
                RETURNING id
                """
            )
        )

    with migrated_database.session() as session:
        stored = session.get(Job, job_id)

        assert stored is not None
        assert stored.location is Location.UK
        assert stored.language is Language.EN
        assert stored.source == "LinkedIn"
        assert stored.date_added == date(2026, 7, 24)
        assert stored.user_decision is UserDecision.UNDECIDED
        assert stored.created_at.microsecond == 0
        assert stored.updated_at.microsecond == 0


def test_round_trips_optional_and_application_fields(
    migrated_database: Database,
) -> None:
    job = Job(
        company="Entreprise SA",
        job_title="Directeur technique",
        location=Location.FR,
        language=Language.FR,
        source="Company website",
        job_url="https://example.com/jobs/42",
        job_description="Direction technique et transformation.",
        date_added=date(2026, 7, 1),
        general_notes="Introduced by a former colleague.",
        user_decision=UserDecision.PURSUE,
        application_status="Second interview",
        application_date=date(2026, 7, 5),
        next_action="Prepare architecture discussion",
        next_action_date=date(2026, 7, 28),
        salary_expectation="CHF 180,000",
        closure_reason=None,
    )

    with migrated_database.session() as session:
        session.add(job)
        session.flush()
        job_id = job.id

    with migrated_database.session() as session:
        stored = session.scalar(select(Job).where(Job.id == job_id))

        assert stored is not None
        assert stored.location is Location.FR
        assert stored.language is Language.FR
        assert stored.user_decision is UserDecision.PURSUE
        assert stored.job_url == "https://example.com/jobs/42"
        assert stored.general_notes == "Introduced by a former colleague."
        assert stored.application_status == "Second interview"
        assert stored.application_date == date(2026, 7, 5)
        assert stored.next_action == "Prepare architecture discussion"
        assert stored.next_action_date == date(2026, 7, 28)
        assert stored.salary_expectation == "CHF 180,000"
        assert stored.closure_reason is None


def test_updates_timestamp_to_current_whole_second(
    migrated_database: Database,
) -> None:
    old_timestamp = datetime(2000, 1, 1)
    job = Job(
        company="Before Ltd",
        job_title="Engineer",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Initial description.",
        date_added=date(2026, 7, 24),
        updated_at=old_timestamp,
    )

    with migrated_database.session() as session:
        session.add(job)
        session.flush()
        job_id = job.id
        created_at = job.created_at

    with migrated_database.session() as session:
        stored = session.get(Job, job_id)
        assert stored is not None
        stored.company = "After Ltd"
        session.flush()
        updated_at = stored.updated_at
        created_at_after_update = stored.created_at

    assert updated_at > old_timestamp
    assert updated_at.microsecond == 0
    assert created_at_after_update == created_at


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("location", "DE"),
        ("language", "DE"),
        ("user_decision", "MAYBE"),
        ("company", "   "),
        ("job_title", ""),
        ("job_description", "  "),
        ("source", ""),
    ],
)
def test_database_rejects_invalid_constrained_values(
    migrated_database: Database,
    column: str,
    invalid_value: str,
) -> None:
    values = {
        "company": "Example Ltd",
        "job_title": "Engineer",
        "location": "UK",
        "language": "EN",
        "source": "LinkedIn",
        "job_description": "Build systems.",
        "date_added": "2026-07-24",
        "user_decision": "UNDECIDED",
    }
    values[column] = invalid_value

    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO jobs (
                        company,
                        job_title,
                        location,
                        language,
                        source,
                        job_description,
                        date_added,
                        user_decision
                    )
                    VALUES (
                        :company,
                        :job_title,
                        :location,
                        :language,
                        :source,
                        :job_description,
                        :date_added,
                        :user_decision
                    )
                    """
                ),
                values,
            )


@pytest.mark.parametrize(
    "missing_column",
    [
        "company",
        "job_title",
        "location",
        "language",
        "source",
        "job_description",
        "date_added",
    ],
)
def test_database_rejects_missing_required_job_fields(
    migrated_database: Database,
    missing_column: str,
) -> None:
    values = {
        "company": "Example Ltd",
        "job_title": "Engineer",
        "location": "UK",
        "language": "EN",
        "source": "LinkedIn",
        "job_description": "Build systems.",
        "date_added": date(2026, 7, 24),
    }
    del values[missing_column]

    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.execute(Job.__table__.insert().values(**values))


def test_migration_schema_and_reversible_upgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "copilot.db"
    status = initialize_database(database_path)
    database = create_database(database_path)

    try:
        inspector = inspect(database.engine)
        columns = {column["name"]: column for column in inspector.get_columns("jobs")}
        checks = {constraint["name"] for constraint in inspector.get_check_constraints("jobs")}

        assert status.current_revision == JOB_REVISION
        assert set(columns) == {
            "id",
            "company",
            "job_title",
            "location",
            "language",
            "source",
            "job_url",
            "job_description",
            "date_added",
            "general_notes",
            "user_decision",
            "application_status",
            "application_date",
            "next_action",
            "next_action_date",
            "salary_expectation",
            "closure_reason",
            "created_at",
            "updated_at",
        }
        assert columns["id"]["primary_key"]
        assert not columns["company"]["nullable"]
        assert not columns["job_description"]["nullable"]
        for field in ("location", "language", "source", "date_added"):
            assert not columns[field]["nullable"]
            assert columns[field]["default"] is None
        assert columns["user_decision"]["default"] is not None
        assert columns["created_at"]["default"] is not None
        assert columns["updated_at"]["default"] is not None
        assert {
            "job_location",
            "job_language",
            "job_user_decision",
            "ck_jobs_company_not_blank",
            "ck_jobs_title_not_blank",
            "ck_jobs_description_not_blank",
            "ck_jobs_source_not_blank",
        } <= checks

        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, FOUNDATION_REVISION)

        assert inspect(database.engine).get_table_names() == ["alembic_version"]
    finally:
        database.dispose()

    upgraded = initialize_database(database_path)
    assert upgraded.previous_revision == FOUNDATION_REVISION
    assert upgraded.current_revision == JOB_REVISION
