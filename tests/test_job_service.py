"""Integration tests for atomic job application-service operations."""

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from job_application_copilot.domain import (
    CreateJob,
    JobFilters,
    Language,
    Location,
    UpdateJob,
    UserDecision,
)
from job_application_copilot.repositories import (
    Database,
    create_database,
)
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import (
    DuplicateJobUrlError,
    JobNotFoundError,
    JobService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def database_and_service(tmp_path: Path) -> tuple[Database, JobService]:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database, JobService(database)
    finally:
        database.dispose()


def create_command(company: str = "Example Ltd") -> CreateJob:
    return CreateJob(
        company=company,
        job_title="Platform Engineer",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Build and operate reliable systems.",
        date_added=date(2026, 7, 24),
        job_url="https://example.com/job",
        general_notes="Initial note",
    )


def update_command() -> UpdateJob:
    return UpdateJob(
        company="Entreprise SA",
        job_title="Directeur technique",
        location=Location.FR,
        language=Language.FR,
        source="Company website",
        job_description="Direction technique.",
        date_added=date(2026, 7, 20),
        job_url=None,
        general_notes=None,
        user_decision=UserDecision.PURSUE,
        application_status="Applied",
        application_date=date(2026, 7, 21),
        next_action="Prepare interview",
        next_action_date=date(2026, 7, 28),
        salary_expectation="EUR 150,000",
        closure_reason=None,
    )


def test_create_and_get_return_readable_job_after_transaction(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service

    created = service.create(create_command())
    stored = service.get(created.id)

    assert created.id is not None
    assert created.company == "Example Ltd"
    assert stored is not None
    assert stored.id == created.id
    assert stored.job_url == "https://example.com/job"
    assert stored.user_decision is UserDecision.UNDECIDED


def test_update_replaces_fields_clears_nullable_values_and_preserves_identity(
    database_and_service: tuple[Database, JobService],
) -> None:
    database, service = database_and_service
    created = service.create(create_command())
    old_timestamp = datetime(2000, 1, 1)
    with database.session() as session:
        stored = session.get(Job, created.id)
        assert stored is not None
        stored.updated_at = old_timestamp
    created_at = created.created_at

    updated = service.update(created.id, update_command())

    assert updated.id == created.id
    assert updated.created_at == created_at
    assert updated.updated_at > old_timestamp
    assert updated.updated_at.microsecond == 0
    assert updated.company == "Entreprise SA"
    assert updated.location is Location.FR
    assert updated.language is Language.FR
    assert updated.job_url is None
    assert updated.general_notes is None
    assert updated.user_decision is UserDecision.PURSUE
    assert updated.application_status == "Applied"
    assert updated.next_action == "Prepare interview"


def test_list_delegates_filters(database_and_service: tuple[Database, JobService]) -> None:
    _, service = database_and_service
    service.create(create_command("Alpha"))
    service.create(
        replace(
            create_command("Beta"),
            location=Location.FR,
            language=Language.FR,
            job_url=None,
        )
    )

    jobs = service.list(JobFilters(location=Location.FR))

    assert [job.company for job in jobs] == ["Beta"]


def test_delete_and_missing_job_errors(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    first = service.create(create_command("First"))
    second = service.create(replace(create_command("Second"), job_url=None))

    service.delete(first.id)

    assert service.get(first.id) is None
    assert service.get(second.id) is not None
    with pytest.raises(JobNotFoundError, match="Job 999"):
        service.update(999, update_command())
    with pytest.raises(JobNotFoundError, match="Job 999"):
        service.delete(999)


def test_create_rejects_exact_duplicate_non_null_url(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    existing = service.create(create_command("First"))

    with pytest.raises(DuplicateJobUrlError) as captured:
        service.create(create_command("Duplicate"))

    assert captured.value.existing_job_id == existing.id
    assert [job.company for job in service.list()] == ["First"]


def test_create_allows_null_and_distinct_urls(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service

    service.create(replace(create_command("No URL 1"), job_url=None))
    service.create(replace(create_command("No URL 2"), job_url=None))
    service.create(create_command("Exact URL"))
    service.create(
        replace(
            create_command("Trailing slash"),
            job_url="https://example.com/job/",
        )
    )

    assert {job.company for job in service.list()} == {
        "No URL 1",
        "No URL 2",
        "Exact URL",
        "Trailing slash",
    }


def test_update_allows_own_url_and_rejects_another_jobs_url(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    first = service.create(create_command("First"))
    second = service.create(
        replace(
            create_command("Second"),
            job_url="https://example.com/second",
        )
    )

    own_url_update = replace(update_command(), job_url=first.job_url)
    service.update(first.id, own_url_update)

    duplicate_update = replace(
        update_command(),
        company="Must roll back",
        job_url=second.job_url,
    )
    with pytest.raises(DuplicateJobUrlError) as captured:
        service.update(first.id, duplicate_update)

    assert captured.value.existing_job_id == second.id
    stored = service.get(first.id)
    assert stored is not None
    assert stored.company == own_url_update.company
    assert stored.job_url == first.job_url


def test_failed_create_rolls_back(database_and_service: tuple[Database, JobService]) -> None:
    _, service = database_and_service

    with pytest.raises(IntegrityError):
        service.create(replace(create_command(), company="   "))

    assert service.list() == []


def test_failed_update_rolls_back_all_changes(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    created = service.create(create_command())
    invalid_update = replace(
        update_command(),
        company="   ",
        job_title="This must also roll back",
    )

    with pytest.raises(IntegrityError):
        service.update(created.id, invalid_update)

    stored = service.get(created.id)
    assert stored is not None
    assert stored.company == "Example Ltd"
    assert stored.job_title == "Platform Engineer"
