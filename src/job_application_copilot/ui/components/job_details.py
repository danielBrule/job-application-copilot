"""Job Details page-content component."""

import logging
import re
from collections.abc import Callable
from html import escape

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError
from streamlit.delta_generator import DeltaGenerator

from job_application_copilot.domain import AssessmentStatus, CvStatus, UserDecision
from job_application_copilot.errors import ApplicationValidationError
from job_application_copilot.observability import get_logger, log_event
from job_application_copilot.repositories.assessment_repository import AssessmentNotFoundError
from job_application_copilot.repositories.job_repository import JobNotFoundError
from job_application_copilot.repositories.models import Cv, Job
from job_application_copilot.services import (
    AssessmentReviewNotEligibleError,
    CvFileMissingError,
    CvFileOpener,
    CvFileOpenError,
    CvGenerationBatchService,
    CvLaneConfigurationError,
    CvService,
    CvUploadService,
    CvUploadValidationError,
    InvalidCvLaneSelectionError,
    JobAssessmentDetail,
    JobService,
)
from job_application_copilot.ui.components.job_form import render_edit_job_form

logger = get_logger(__name__)
LOAD_ERROR_MESSAGE = "The job could not be loaded. See the private UI log for details."
REVIEW_FLOW_QUERY_PARAM = "review_flow"
ASSESSMENT_REVIEW_FLOW = "assessment"
CV_REVIEW_FLOW = "cv"
ASSESSMENT_REVIEW_QUEUE_SESSION_KEY = "assessment_review_queue_job_ids"
CV_REVIEW_QUEUE_SESSION_KEY = "cv_review_queue_job_ids"


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


def render_job_details(
    service: JobService,
    cv_service: CvService,
    upload_service: CvUploadService,
    opener: CvFileOpener,
    generation_service: CvGenerationBatchService,
) -> None:
    """Load and render the editable Job Details page."""

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

    _render_job_details_heading(detail.job)
    default_tab = "CV" if st.query_params.get("tab") == "cv" else "Job"
    job_tab, assessment_tab, cv_tab = st.tabs(["Job", "Assessment", "CV"], default=default_tab)
    with job_tab:
        render_edit_job_form(detail.job, service)
    with assessment_tab:
        render_assessment_detail(detail, service)
    with cv_tab:
        _render_cv_tab(detail, cv_service, upload_service, opener, generation_service)


def _render_job_details_heading(job: Job) -> None:
    """Render the title, linking the job title to its original posting when available."""

    if job.job_url is None:
        st.title(f"Job details — {job.job_title} ({job.company})")
        return
    st.markdown(
        "# Job details — "
        f'<a href="{escape(job.job_url, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer">{escape(job.job_title)}</a> ({escape(job.company)})',
        unsafe_allow_html=True,
    )


def _render_cv_tab(
    detail: JobAssessmentDetail,
    cv_service: CvService,
    upload_service: CvUploadService,
    opener: CvFileOpener,
    generation_service: CvGenerationBatchService,
) -> None:
    """Render CV actions from the durable active-CV state."""

    cv = cv_service.get_for_job(detail.job.id)
    if cv is None:
        st.info("No CV is associated with this job yet.")
        _render_cv_generation(detail.job.id, generation_service, regenerate=False)
        with st.form(f"upload_cv_{detail.job.id}", clear_on_submit=True):
            upload = st.file_uploader("Existing CV (DOCX)", type=["docx"])
            submitted = st.form_submit_button("Upload existing CV")
        if submitted:
            if upload is None:
                st.error("Choose a DOCX file to upload.")
            else:
                try:
                    upload_service.upload(
                        job_id=detail.job.id, filename=upload.name, content=upload.getvalue()
                    )
                except CvUploadValidationError as error:
                    st.error(str(error))
                except SQLAlchemyError:
                    logger.exception("cv_upload_failed job_id=%s", detail.job.id)
                    st.error("The CV could not be saved. See the private UI log for details.")
                else:
                    st.rerun()
        return

    st.caption(f"Status: {_label(cv.status.value)}")
    if cv.status is CvStatus.FAILED:
        st.error(cv.error_message or "CV generation failed.")
        _render_cv_generation(detail.job.id, generation_service, regenerate=True)
        return
    if cv.status in {CvStatus.PENDING, CvStatus.GENERATING, CvStatus.SELECTED}:
        st.info("CV generation is in progress.")
        return

    st.write(f"**Filename:** {cv.file_name}")
    st.write(f"**Local path:** {cv.file_path}")
    st.write(f"**Source:** {_label(cv.source.value)}")
    if st.button("Open CV", key=f"open_cv_{detail.job.id}"):
        try:
            opener.open(cv.file_path or "")
        except (CvFileOpenError, CvFileMissingError) as error:
            st.error(str(error))
    if cv.status in {CvStatus.READY_FOR_REVIEW, CvStatus.APPROVED}:
        _render_cv_review_navigation(detail.job.id, cv_service)
    if cv.status is CvStatus.READY_FOR_REVIEW:
        with st.expander("Review notes (optional)", expanded=False):
            st.text_area("Review notes", key=f"review_notes_{detail.job.id}")
    else:
        st.write(f"**Approved at:** {cv.approved_at}")
        if cv.review_notes:
            st.write(f"**Review notes:** {cv.review_notes}")
    if _can_record_application(detail, cv):
        _render_application_status(detail.job.id, detail.job.application_status, cv_service)


def _can_record_application(detail: JobAssessmentDetail, cv: Cv) -> bool:
    """Return whether assessment and completed CV work permit recording an application."""

    return (
        detail.assessment is not None
        and detail.assessment.status is AssessmentStatus.ASSESSED
        and cv.status in {CvStatus.READY_FOR_REVIEW, CvStatus.APPROVED}
    )


def _render_application_status(
    job_id: int,
    current_status: str | None,
    service: CvService,
) -> None:
    """Persist fixed application tracking states directly from the selector."""

    st.markdown("#### Application")
    options = (None, "Applied", "1st round", "2nd round", "3rd round", "4th round", "Rejected")
    st.selectbox(
        "Application status",
        options=options,
        index=options.index(current_status) if current_status in options else 0,
        format_func=lambda status: status or "None",
        key=f"application_status_option_{job_id}",
        on_change=_record_application_status,
        args=(job_id, service),
    )
    if current_status == "Applied":
        st.caption("Application date is recorded automatically when Applied is selected.")


def _record_application_status(job_id: int, service: CvService) -> None:
    status = st.session_state[f"application_status_option_{job_id}"]
    review_notes = st.session_state.get(f"review_notes_{job_id}")
    try:
        service.record_application_status(job_id, status=status, review_notes=review_notes)
    except ApplicationValidationError as error:
        st.error(str(error))
    except JobNotFoundError:
        st.error("This job is no longer available. Refresh the page and try again.")
    except SQLAlchemyError:
        logger.exception("application_status_save_failed job_id=%s", job_id)
        st.error("The application status could not be saved. See the private UI log for details.")
    else:
        return


def _render_cv_generation(
    job_id: int, service: CvGenerationBatchService, *, regenerate: bool
) -> None:
    label = "Regenerate CV" if regenerate else "Generate CV"
    confirmed = st.checkbox(
        f"I want to {label.lower()} for this job.",
        key=f"confirm_{label}_{job_id}",
    )
    if st.button(label, key=f"{label}_{job_id}", disabled=not confirmed):
        result = (
            service.queue_regeneration_selected((job_id,))
            if regenerate
            else service.queue_selected((job_id,))
        )
        if result.batch_id is None:
            st.warning("This job is not currently eligible for CV generation.")
        else:
            st.success("CV generation has been queued.")


def _render_cv_review_navigation(job_id: int, service: CvService) -> None:
    try:
        queue = _review_queue(
            CV_REVIEW_FLOW,
            job_id,
            service.default_application_status_review_job_ids,
        )
    except SQLAlchemyError:
        logger.exception("cv_review_navigation_load_failed job_id=%s", job_id)
        st.warning("Review navigation is temporarily unavailable. Refresh the page and try again.")
        return
    navigation = _circular_review_navigation(queue, job_id)
    if navigation is None:
        return
    previous_job_id, next_job_id = navigation
    previous, next_job = st.columns(2)
    with previous:
        if st.button("Previous CV", key=f"previous_cv_review_{job_id}"):
            st.switch_page(
                "pages/job_details.py",
                query_params={
                    "job_id": str(previous_job_id),
                    "tab": "cv",
                    REVIEW_FLOW_QUERY_PARAM: CV_REVIEW_FLOW,
                },
            )
    with next_job:
        if st.button(
            "Next CV",
            key=f"next_cv_review_{job_id}",
        ):
            st.switch_page(
                "pages/job_details.py",
                query_params={
                    "job_id": str(next_job_id),
                    "tab": "cv",
                    REVIEW_FLOW_QUERY_PARAM: CV_REVIEW_FLOW,
                },
            )


def render_assessment_detail(detail: JobAssessmentDetail, service: JobService) -> None:
    """Render the current assessment without allowing model-output edits."""

    assessment = detail.assessment
    st.subheader("Assessment")
    if assessment is None:
        st.info("This job has not been assessed yet.")
        return

    if detail.is_stale:
        st.warning(
            "This assessment is stale because assessment-relevant job details changed after it "
            "was completed. The previous valid result remains available until reassessment succeeds."
        )
    if assessment.status.value == "FAILED":
        st.caption(f"Status: {_label(assessment.status.value)}")
        st.error(assessment.error_message or "Assessment did not complete.")
        return
    if assessment.status.value != "ASSESSED":
        st.caption(f"Status: {_label(assessment.status.value)}")
        st.info("Assessment output will appear here after processing completes.")
        return

    assert assessment.model_relevance is not None
    assert assessment.decision is not None
    _render_assessment_navigation(detail, service)
    cv_lanes = _available_cv_lanes(service)
    _render_auto_saving_decision(detail, service, cv_lanes)
    model_columns = st.columns(3)
    model_columns[0].metric("Model relevance", _label(assessment.model_relevance.value))
    model_columns[1].metric("Recommendation", _label(assessment.decision.value))
    model_columns[2].metric("Fit score", _score(assessment.fit_score))
    summary_columns = st.columns(3)
    _render_summary(summary_columns[0], "Role snapshot", assessment.role_snapshot)
    _render_summary(summary_columns[1], "Real mandate", assessment.real_mandate)
    _render_summary(summary_columns[2], "Recommendation rationale", assessment.decision_reason)

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

    st.markdown("#### Traceability")
    st.write(f"**Document A version:** {assessment.document_a_version}")
    st.write(f"**Assessment prompt version:** {assessment.prompt_version}")
    st.write(f"**Model:** {assessment.model_name}")
    st.write(f"**Assessed at:** {assessment.assessed_at}")
    _render_review_details(detail, service, cv_lanes)


def _available_cv_lanes(service: JobService) -> tuple[str, ...]:
    """Return selectable lanes, reporting unavailable routing safely."""

    try:
        return service.available_cv_lanes()
    except CvLaneConfigurationError as error:
        st.warning(str(error))
        return ()


def _render_auto_saving_decision(
    detail: JobAssessmentDetail,
    service: JobService,
    cv_lanes: tuple[str, ...],
) -> None:
    """Save a changed user decision immediately when a CV lane catalogue exists."""

    assert detail.assessment is not None
    decision = st.selectbox(
        "Decision",
        options=tuple(UserDecision),
        index=tuple(UserDecision).index(detail.job.user_decision),
        format_func=_decision_label,
        disabled=not cv_lanes,
        key=f"human_review_decision_{detail.job.id}",
    )
    if decision is detail.job.user_decision or not cv_lanes:
        return
    _save_human_review(
        detail,
        service,
        decision,
        detail.assessment.assessment_notes,
        _default_lane(detail, cv_lanes),
    )


def _render_review_details(
    detail: JobAssessmentDetail, service: JobService, cv_lanes: tuple[str, ...]
) -> None:
    """Render optional notes and lane controls after the assessment details."""

    assert detail.assessment is not None
    if not cv_lanes:
        return
    with st.form(f"human_review_{detail.job.id}_form"):
        assessment_notes = st.text_area(
            "Assessment notes", value=detail.assessment.assessment_notes or ""
        )
        default_lane = _default_lane(detail, cv_lanes)
        selected_cv_lane = st.selectbox(
            "Selected CV lane", options=cv_lanes, index=cv_lanes.index(default_lane)
        )
        save = st.form_submit_button("Save review details")
    if save:
        _save_human_review(
            detail, service, detail.job.user_decision, assessment_notes, selected_cv_lane
        )


def _default_lane(detail: JobAssessmentDetail, cv_lanes: tuple[str, ...]) -> str:
    assert detail.assessment is not None
    return next(
        (
            lane
            for lane in (
                detail.assessment.selected_cv_lane,
                detail.assessment.recommended_document_b_lane,
            )
            if lane in cv_lanes
        ),
        cv_lanes[0],
    )


def _save_human_review(
    detail: JobAssessmentDetail,
    service: JobService,
    user_decision: UserDecision,
    assessment_notes: str | None,
    selected_cv_lane: str,
) -> None:
    try:
        service.update_human_review(
            detail.job.id,
            user_decision=user_decision,
            assessment_notes=assessment_notes,
            selected_cv_lane=selected_cv_lane,
        )
    except (AssessmentReviewNotEligibleError, InvalidCvLaneSelectionError) as error:
        st.error(str(error))
    except (JobNotFoundError, AssessmentNotFoundError):
        st.error("The assessment is no longer available. Refresh the page and try again.")
    except SQLAlchemyError:
        logger.exception("human_review_save_failed job_id=%s", detail.job.id)
        st.error("The human review could not be saved. See the private UI log for details.")
    else:
        st.rerun()


def _render_assessment_navigation(detail: JobAssessmentDetail, service: JobService) -> None:
    """Render circular neighbours from the active assessment-review snapshot."""

    try:
        queue = _review_queue(
            ASSESSMENT_REVIEW_FLOW,
            detail.job.id,
            service.assessment_review_job_ids,
        )
    except SQLAlchemyError:
        logger.exception("assessment_review_navigation_load_failed job_id=%s", detail.job.id)
        st.warning("Review navigation is temporarily unavailable. Refresh the page and try again.")
        return
    navigation = _circular_review_navigation(queue, detail.job.id)
    if navigation is None:
        return
    previous_job_id, next_job_id = navigation

    previous_column, next_column, _ = st.columns((1, 1, 4))
    with previous_column:
        if st.button(
            "Previous",
            key=f"previous_assessment_review_{detail.job.id}",
        ):
            st.switch_page(
                "pages/job_details.py",
                query_params={
                    "job_id": str(previous_job_id),
                    REVIEW_FLOW_QUERY_PARAM: ASSESSMENT_REVIEW_FLOW,
                },
            )
    with next_column:
        if st.button(
            "Next",
            key=f"next_assessment_review_{detail.job.id}",
        ):
            st.switch_page(
                "pages/job_details.py",
                query_params={
                    "job_id": str(next_job_id),
                    REVIEW_FLOW_QUERY_PARAM: ASSESSMENT_REVIEW_FLOW,
                },
            )


def _review_queue(
    flow: str,
    job_id: int,
    load_current_queue: Callable[[], tuple[int, ...]],
) -> tuple[int, ...]:
    """Return one tab's stable review snapshot, creating it at review entry."""

    session_key = (
        ASSESSMENT_REVIEW_QUEUE_SESSION_KEY
        if flow == ASSESSMENT_REVIEW_FLOW
        else CV_REVIEW_QUEUE_SESSION_KEY
    )
    queue = tuple(st.session_state.get(session_key, ()))
    if job_id in queue:
        return queue
    active_flow = st.query_params.get(REVIEW_FLOW_QUERY_PARAM)
    if active_flow not in (None, flow):
        return ()
    queue = load_current_queue()
    if job_id not in queue:
        return ()
    st.session_state[session_key] = queue
    return queue


def _circular_review_navigation(queue: tuple[int, ...], job_id: int) -> tuple[int, int] | None:
    """Return circular neighbours for a job in a saved review queue."""

    if not queue or job_id not in queue:
        return None
    position = queue.index(job_id)
    return queue[position - 1], queue[(position + 1) % len(queue)]


def _render_summary(column: DeltaGenerator, label: str, value: str | None) -> None:
    """Present a single summary as text and multi-line summaries as capped bullets."""

    with column:
        st.write(f"**{label}**")
        bullets = summary_bullets(value)
        if len(bullets) == 1:
            st.write(bullets[0])
        elif bullets:
            st.markdown("\n".join(f"- {bullet}" for bullet in bullets))
        else:
            st.caption("Not reported.")


def summary_bullets(value: str | None) -> tuple[str, ...]:
    """Normalize presentation-only summary lines and cap them at ten bullets."""

    if value is None:
        return ()
    bullets: list[str] = []
    for line in value.splitlines():
        normalized = re.sub(r"^\s*(?:[-*â€¢]|\d+[.)])\s*", "", line).strip()
        normalized = " ".join(normalized.split())
        if normalized:
            bullets.append(normalized)
    if not bullets and (normalized_value := " ".join(value.split())):
        bullets.append(normalized_value)
    return tuple(bullets[:10])


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


def _decision_label(value: UserDecision) -> str:
    if value is UserDecision.PURSUE:
        return "Pursue and select for CV generation"
    return _label(value.value)
