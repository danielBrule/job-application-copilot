"""Stable job domain values."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Location(StrEnum):
    """Supported job locations."""

    UK = "UK"
    FR = "FR"
    CH = "CH"


class Language(StrEnum):
    """Supported job and CV languages."""

    EN = "EN"
    FR = "FR"


class UserDecision(StrEnum):
    """Human application decision, independent of model recommendations."""

    UNDECIDED = "UNDECIDED"
    PURSUE = "PURSUE"
    DO_NOT_PURSUE = "DO_NOT_PURSUE"


@dataclass(frozen=True, slots=True)
class CreateJob:
    """Complete values used to create a persisted job."""

    company: str
    job_title: str
    location: Location
    language: Language
    source: str
    job_description: str
    date_added: date
    job_url: str | None = None
    general_notes: str | None = None
    user_decision: UserDecision = UserDecision.UNDECIDED
    application_status: str | None = None
    application_date: date | None = None
    next_action: str | None = None
    next_action_date: date | None = None
    salary_expectation: str | None = None
    closure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateJob:
    """Complete replacement values for editable job fields."""

    company: str
    job_title: str
    location: Location
    language: Language
    source: str
    job_description: str
    date_added: date
    job_url: str | None
    general_notes: str | None
    user_decision: UserDecision
    application_status: str | None
    application_date: date | None
    next_action: str | None
    next_action_date: date | None
    salary_expectation: str | None
    closure_reason: str | None


@dataclass(frozen=True, slots=True)
class JobFilters:
    """Filters supported entirely by the current jobs table."""

    text: str | None = None
    location: Location | None = None
    language: Language | None = None
    source: str | None = None
    user_decision: UserDecision | None = None
    application_status: str | None = None
