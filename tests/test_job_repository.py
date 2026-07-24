"""Integration tests for session-scoped job persistence queries."""

from datetime import date
from pathlib import Path

import pytest

from job_application_copilot.domain import (
    JobFilters,
    Language,
    Location,
    UserDecision,
)
from job_application_copilot.repositories import (
    Database,
    JobNotFoundError,
    JobRepository,
    create_database,
)
from job_application_copilot.repositories.models import Job
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


def make_job(
    company: str,
    *,
    job_title: str = "Platform Engineer",
    location: Location = Location.UK,
    language: Language = Language.EN,
    source: str = "LinkedIn",
    date_added: date = date(2026, 7, 24),
    user_decision: UserDecision = UserDecision.UNDECIDED,
    application_status: str | None = None,
) -> Job:
    return Job(
        company=company,
        job_title=job_title,
        location=location,
        language=language,
        source=source,
        job_description="Build reliable systems.",
        date_added=date_added,
        user_decision=user_decision,
        application_status=application_status,
    )


def test_add_get_and_require_job(migrated_database: Database) -> None:
    with migrated_database.session() as session:
        repository = JobRepository(session)
        added = repository.add(make_job("Example Ltd"))
        job_id = added.id

        assert repository.get(job_id) is added
        assert repository.require(job_id) is added

    with migrated_database.session() as session:
        stored = JobRepository(session).get(job_id)

        assert stored is not None
        assert stored.company == "Example Ltd"


def test_get_returns_none_and_require_raises_for_unknown_job(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        repository = JobRepository(session)

        assert repository.get(999) is None
        with pytest.raises(JobNotFoundError, match="Job 999"):
            repository.require(999)


def test_get_by_url_uses_exact_matching(migrated_database: Database) -> None:
    with migrated_database.session() as session:
        repository = JobRepository(session)
        job = make_job("Exact URL")
        job.job_url = "https://example.com/job"
        repository.add(job)

        assert repository.get_by_url("https://example.com/job") is job
        assert repository.get_by_url("https://example.com/job/") is None
        assert repository.get_by_url("HTTPS://example.com/job") is None


def test_lists_jobs_newest_first_with_stable_id_tiebreaker(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        repository = JobRepository(session)
        repository.add(make_job("Older", date_added=date(2026, 7, 20)))
        repository.add(make_job("Newest first", date_added=date(2026, 7, 24)))
        repository.add(make_job("Newest second", date_added=date(2026, 7, 24)))

        companies = [job.company for job in repository.list()]

    assert companies == ["Newest second", "Newest first", "Older"]


@pytest.mark.parametrize(
    ("filters", "expected_companies"),
    [
        (JobFilters(text="PLATFORM"), {"Alpha", "Gamma"}),
        (JobFilters(text="data"), {"Beta"}),
        (JobFilters(location=Location.UK), {"Alpha", "Gamma"}),
        (JobFilters(language=Language.FR), {"Beta", "Gamma"}),
        (JobFilters(source="Company website"), {"Beta"}),
        (JobFilters(user_decision=UserDecision.PURSUE), {"Alpha", "Gamma"}),
        (JobFilters(application_status="Applied"), {"Alpha", "Gamma"}),
        (
            JobFilters(
                location=Location.UK,
                language=Language.FR,
                source="LinkedIn",
                user_decision=UserDecision.PURSUE,
                application_status="Applied",
            ),
            {"Gamma"},
        ),
    ],
)
def test_filters_jobs(
    migrated_database: Database,
    filters: JobFilters,
    expected_companies: set[str],
) -> None:
    with migrated_database.session() as session:
        repository = JobRepository(session)
        repository.add(
            make_job(
                "Alpha",
                location=Location.UK,
                language=Language.EN,
                user_decision=UserDecision.PURSUE,
                application_status="Applied",
            )
        )
        repository.add(
            make_job(
                "Beta",
                job_title="Data Engineer",
                location=Location.FR,
                language=Language.FR,
                source="Company website",
            )
        )
        repository.add(
            make_job(
                "Gamma",
                location=Location.UK,
                language=Language.FR,
                user_decision=UserDecision.PURSUE,
                application_status="Applied",
            )
        )

        companies = {job.company for job in repository.list(filters)}

    assert companies == expected_companies


@pytest.mark.parametrize(
    ("search_text", "expected_company"),
    [
        ("100%", "100% Genuine"),
        ("A_B", "A_B Consulting"),
    ],
)
def test_text_filter_treats_sql_wildcards_literally(
    migrated_database: Database,
    search_text: str,
    expected_company: str,
) -> None:
    with migrated_database.session() as session:
        repository = JobRepository(session)
        repository.add(make_job("100% Genuine"))
        repository.add(make_job("100 Percent Genuine"))
        repository.add(make_job("A_B Consulting"))
        repository.add(make_job("ACB Consulting"))

        companies = [job.company for job in repository.list(JobFilters(text=search_text))]

    assert companies == [expected_company]


def test_delete_removes_only_selected_job(migrated_database: Database) -> None:
    with migrated_database.session() as session:
        repository = JobRepository(session)
        removed = repository.add(make_job("Remove"))
        retained = repository.add(make_job("Retain"))
        removed_id = removed.id
        retained_id = retained.id
        repository.delete(removed)

    with migrated_database.session() as session:
        repository = JobRepository(session)

        assert repository.get(removed_id) is None
        assert repository.require(retained_id).company == "Retain"
