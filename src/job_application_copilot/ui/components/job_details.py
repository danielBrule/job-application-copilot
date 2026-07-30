"""Job Details page-content component."""

import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.observability import get_logger, log_event
from job_application_copilot.repositories.job_repository import JobNotFoundError
from job_application_copilot.services import JobAssessmentDetail, JobService
from job_application_copilot.ui.components.job_form import render_edit_job_form

logger = get_logger(__name__)
LOAD_ERROR_MESSAGE = "The job could not be loaded. See the private UI log for details."


def parse_job_id(value: str | None) -> int:
    """Parse a positive job identifier from a query parameter."""

    if value is None:
        raise ValueError("A job ID is required.")
    try:
        job_id = int(value)
    except ValueError as error:
        raise ValueError("The job ID must be a positive integer.") from error
    if job_id <= 0:
        raise ValueError("The job ID must be a positive integer.")
    return job_id


def render_job_details(service: JobService) -> None:
    """Load and render the editable Job Details page."""

    st.title("Job details")
    try:
        job_id = parse_job_id(st.query_params.get("job_id"))
    except ValueError as error:
        st.error(str(error))
        st.page_link("pages/jobs.py", label="Back to Jobs")
        return

    try:
        detail = service.assessment_detail(job_id)
    except JobNotFoundError:
        log_event(logger, logging.WARNING, "job_not_found", job_id=job_id)
        st.error(f"Job {job_id} does not exist.")
        st.page_link("pages/jobs.py", label="Back to Jobs")
        return
    except SQLAlchemyError:
        logger.exception("job_load_failed job_id=%s", job_id)
        st.error(LOAD_ERROR_MESSAGE)
        st.page_link("pages/jobs.py", label="Back to Jobs")
        return

    job_tab, assessment_tab = st.tabs(["Job", "Assessment"])
    with job_tab:
        render_edit_job_form(detail.job, service)
    with assessment_tab:
        render_assessment_detail(detail)


def render_assessment_detail(detail: JobAssessmentDetail) -> None:
    """Render the current assessment without allowing model-output edits."""

    assessment = detail.assessment
    st.subheader("Assessment")
    if assessment is None:
        st.info("This job has not been assessed yet.")
        return

    st.caption(f"Status: {_label(assessment.status.value)}")
    if detail.is_stale:
        st.warning(
            "This assessment is stale because assessment-relevant job details changed after it "
            "was completed. The previous valid result remains available until reassessment succeeds."
        )
    if assessment.status.value == "FAILED":
        st.error(assessment.error_message or "Assessment did not complete.")
        return
    if assessment.status.value != "ASSESSED":
        st.info("Assessment output will appear here after processing completes.")
        return

    assert assessment.model_relevance is not None
    assert assessment.decision is not None
    st.markdown("#### Model assessment")
    model_columns = st.columns(3)
    model_columns[0].metric("Model relevance", _label(assessment.model_relevance.value))
    model_columns[1].metric("Recommendation", _label(assessment.decision.value))
    model_columns[2].metric("Fit score", _score(assessment.fit_score))
    st.write("**Role snapshot**")
    st.write(assessment.role_snapshot)
    st.write("**Real mandate behind the title**")
    st.write(assessment.real_mandate)
    st.write("**Recommendation rationale**")
    st.write(assessment.decision_reason)

    st.markdown("#### Role and fit")
    st.write(f"**Primary role family:** {assessment.primary_role_family}")
    st.write(f"**Secondary role family:** {_optional(assessment.secondary_role_family)}")
    st.write(f"**Technical bar:** {assessment.technical_bar}")
    score_columns = st.columns(5)
    score_columns[0].metric("Seniority fit", _score(assessment.seniority_fit))
    score_columns[1].metric("Technical-bar fit", _score(assessment.tech_bar_fit))
    score_columns[2].metric("Priority score", _score(assessment.priority_score))
    score_columns[3].metric(
        "Interview probability",
        f"{assessment.interview_probability_low}–{assessment.interview_probability_high} / 10",
    )
    score_columns[4].metric(
        "Interview confidence", _score(assessment.interview_probability_confidence)
    )

    st.markdown("#### Signals and risks")
    _render_items("Strong fit signals", assessment.strong_fit_signals)
    _render_items("Red flags", assessment.red_flags)
    _render_items("Sustainability risks", assessment.sustainability_risks)

    st.markdown("#### Evidence and CV handover")
    st.write(f"**Evidence confidence:** {_score(assessment.evidence_confidence)}")
    st.write("**Evidence anchors**")
    if assessment.evidence_anchors:
        st.dataframe(assessment.evidence_anchors, hide_index=True, width="stretch")
    else:
        st.caption("No evidence anchors were reported.")
    _render_items("Evidence gaps", assessment.evidence_gaps)
    st.write(f"**Recommended Document B lane:** {assessment.recommended_document_b_lane}")
    st.write(f"**Secondary CV angle:** {_optional(assessment.secondary_cv_angle)}")
    _render_items("Overclaiming constraints", assessment.overclaiming_risks)

    st.markdown("#### Human choices")
    st.write(f"**Relevance override:** {_optional_label(detail.job.relevance_override)}")
    st.write(f"**Effective relevance:** {_effective_relevance(detail)}")
    st.write(f"**User decision:** {_label(detail.job.user_decision.value)}")
    st.write(f"**Selected CV lane:** {_optional(assessment.selected_cv_lane)}")
    st.write(f"**Assessment notes:** {_optional(assessment.assessment_notes)}")

    st.markdown("#### Traceability")
    st.write(f"**Document A version:** {assessment.document_a_version}")
    st.write(f"**Assessment prompt version:** {assessment.prompt_version}")
    st.write(f"**Model:** {assessment.model_name}")
    st.write(f"**Assessed at:** {assessment.assessed_at}")


def _render_items(label: str, values: list[str]) -> None:
    """Render a stored list while preserving an explicit empty result."""

    st.write(f"**{label}**")
    if not values:
        st.caption("None reported.")
        return
    st.markdown("\n".join(f"- {value}" for value in values))


def _effective_relevance(detail: JobAssessmentDetail) -> str:
    if detail.job.relevance_override is not None:
        return _label(detail.job.relevance_override.value)
    assert detail.assessment is not None
    assert detail.assessment.model_relevance is not None
    return _label(detail.assessment.model_relevance.value)


def _optional(value: object | None) -> str:
    return str(value) if value is not None else "Not set"


def _optional_label(value: object | None) -> str:
    return _label(str(value)) if value is not None else "Use model relevance"


def _score(value: int | None) -> str:
    return f"{value} / 10" if value is not None else "Not available"


def _label(value: str) -> str:
    return value.replace("_", " ").title()
