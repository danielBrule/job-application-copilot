"""Tests for Jobs dashboard filter normalization."""

from datetime import date

from job_application_copilot.domain import Language, Location, UserDecision
from job_application_copilot.repositories.models import Job
from job_application_copilot.ui.components.job_filters import (
    available_sources,
    build_job_filters,
    has_active_filters,
)


def make_job(source: str) -> Job:
    return Job(
        company="Example Ltd",
        job_title="Platform Engineer",
        location=Location.UK,
        language=Language.EN,
        source=source,
        job_description="Build reliable systems.",
        date_added=date(2026, 7, 24),
    )


def test_available_sources_are_unique_and_case_insensitively_sorted() -> None:
    sources = available_sources(
        [
            make_job("LinkedIn"),
            make_job("company website"),
            make_job("Agency"),
            make_job("LinkedIn"),
        ]
    )

    assert sources == ("Agency", "company website", "LinkedIn")


def test_build_job_filters_trims_text_and_preserves_choices() -> None:
    filters = build_job_filters(
        text=" platform ",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        user_decision=UserDecision.PURSUE,
        application_status=" interview ",
    )

    assert filters.text == "platform"
    assert filters.location is Location.UK
    assert filters.language is Language.EN
    assert filters.source == "LinkedIn"
    assert filters.user_decision is UserDecision.PURSUE
    assert filters.application_status == "interview"
    assert has_active_filters(filters)


def test_blank_filter_values_are_inactive() -> None:
    filters = build_job_filters(
        text=" ",
        location=None,
        language=None,
        source=None,
        user_decision=None,
        application_status="\n",
    )

    assert not has_active_filters(filters)
