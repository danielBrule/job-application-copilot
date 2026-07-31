"""Jobs dashboard filter component and normalization."""

from collections.abc import Callable, Iterable

import streamlit as st

from job_application_copilot.domain import (
    AssessmentDecision,
    DashboardAssessmentStatus,
    JobFilters,
    Language,
    Location,
    UserDecision,
)
from job_application_copilot.repositories.models import Job

FILTER_TEXT_KEY = "jobs_filter_text"
FILTER_LOCATION_KEY = "jobs_filter_location"
FILTER_LANGUAGE_KEY = "jobs_filter_language"
FILTER_SOURCE_KEY = "jobs_filter_source"
FILTER_USER_DECISION_KEY = "jobs_filter_user_decision"
FILTER_APPLICATION_STATUS_KEY = "jobs_filter_application_status"
FILTER_ASSESSMENT_STATUS_KEY = "jobs_filter_assessment_status"
FILTER_ASSESSMENT_DECISION_KEY = "jobs_filter_assessment_decision"
CLEAR_FILTERS_KEY = "jobs_clear_filters"
FILTER_DEFAULTS: dict[str, object] = {
    FILTER_TEXT_KEY: "",
    FILTER_LOCATION_KEY: None,
    FILTER_LANGUAGE_KEY: None,
    FILTER_SOURCE_KEY: None,
    FILTER_USER_DECISION_KEY: None,
    FILTER_APPLICATION_STATUS_KEY: "",
    FILTER_ASSESSMENT_STATUS_KEY: None,
    FILTER_ASSESSMENT_DECISION_KEY: None,
}
USER_DECISION_LABELS = {
    UserDecision.UNDECIDED: "Undecided",
    UserDecision.PURSUE: "Pursue",
    UserDecision.DO_NOT_PURSUE: "Do not pursue",
}


def available_sources(jobs: Iterable[Job]) -> tuple[str, ...]:
    """Return unique stored sources in deterministic case-insensitive order."""

    return tuple(sorted({job.source for job in jobs}, key=str.casefold))


def build_job_filters(
    *,
    text: str | None,
    location: Location | None,
    language: Language | None,
    source: str | None,
    user_decision: UserDecision | None,
    application_status: str | None,
    assessment_status: DashboardAssessmentStatus | None = None,
    assessment_decision: AssessmentDecision | None = None,
) -> JobFilters:
    """Normalize Streamlit widget values into the repository filter contract."""

    return JobFilters(
        text=_optional_text(text),
        location=location,
        language=language,
        source=source,
        user_decision=user_decision,
        application_status=_optional_text(application_status),
        assessment_status=assessment_status,
        assessment_decision=assessment_decision,
    )


def has_active_filters(filters: JobFilters) -> bool:
    """Return whether at least one dashboard filter is active."""

    return any(
        value is not None
        for value in (
            filters.text,
            filters.location,
            filters.language,
            filters.source,
            filters.user_decision,
            filters.application_status,
            filters.assessment_status,
            filters.assessment_decision,
        )
    )


def render_job_filters(
    sources: tuple[str, ...],
    on_filter_change: Callable[[], None],
) -> JobFilters:
    """Render filter controls and return their normalized values."""

    _discard_stale_source(sources)
    with st.expander("Filters", expanded=False):
        first_column, second_column, third_column = st.columns(3)
        with first_column:
            text = st.text_input(
                "Search company or job title",
                key=FILTER_TEXT_KEY,
                on_change=on_filter_change,
            )
        with second_column:
            location = st.selectbox(
                "Location",
                options=[None, *Location],
                format_func=_optional_label,
                key=FILTER_LOCATION_KEY,
                on_change=on_filter_change,
            )
        with third_column:
            language = st.selectbox(
                "Language",
                options=[None, *Language],
                format_func=_optional_label,
                key=FILTER_LANGUAGE_KEY,
                on_change=on_filter_change,
            )

        fourth_column, fifth_column, sixth_column = st.columns(3)
        with fourth_column:
            source = st.selectbox(
                "Source",
                options=[None, *sources],
                format_func=_optional_label,
                key=FILTER_SOURCE_KEY,
                on_change=on_filter_change,
            )
        with fifth_column:
            user_decision = st.selectbox(
                "User decision",
                options=[None, *UserDecision],
                format_func=_user_decision_label,
                key=FILTER_USER_DECISION_KEY,
                on_change=on_filter_change,
            )
        with sixth_column:
            application_status = st.text_input(
                "Application status",
                key=FILTER_APPLICATION_STATUS_KEY,
                on_change=on_filter_change,
            )

        seventh_column, eighth_column = st.columns(2)
        with seventh_column:
            assessment_status = st.selectbox(
                "Assessment status",
                options=[None, *DashboardAssessmentStatus],
                format_func=_assessment_status_label,
                key=FILTER_ASSESSMENT_STATUS_KEY,
                on_change=on_filter_change,
            )
        with eighth_column:
            assessment_decision = st.selectbox(
                "Model decision",
                options=[None, *AssessmentDecision],
                format_func=_optional_label,
                key=FILTER_ASSESSMENT_DECISION_KEY,
                on_change=on_filter_change,
            )

        st.button(
            "Clear filters",
            key=CLEAR_FILTERS_KEY,
            on_click=_clear_filters,
            args=(on_filter_change,),
        )

    return build_job_filters(
        text=text,
        location=location,
        language=language,
        source=source,
        user_decision=user_decision,
        application_status=application_status,
        assessment_status=assessment_status,
        assessment_decision=assessment_decision,
    )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _optional_label(value: object) -> str:
    return "All" if value is None else str(value)


def _user_decision_label(value: object) -> str:
    if value is None:
        return "All"
    if isinstance(value, UserDecision):
        return USER_DECISION_LABELS[value]
    return str(value)


def _assessment_status_label(value: object) -> str:
    if value is None:
        return "All"
    if value is DashboardAssessmentStatus.NOT_ASSESSED:
        return "Not assessed"
    return str(value).title()


def _discard_stale_source(sources: tuple[str, ...]) -> None:
    selected_source = st.session_state.get(FILTER_SOURCE_KEY)
    if selected_source is not None and selected_source not in sources:
        st.session_state[FILTER_SOURCE_KEY] = None


def _clear_filters(on_filter_change: Callable[[], None]) -> None:
    for key, value in FILTER_DEFAULTS.items():
        st.session_state[key] = value
    on_filter_change()
