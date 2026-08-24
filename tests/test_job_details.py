"""Tests for Job Details input handling and assessment view state."""

from datetime import date

import pytest

from job_application_copilot.domain import (
    AssessmentStatus,
    CvSource,
    CvStatus,
    Language,
    Location,
    Relevance,
)
from job_application_copilot.repositories import AssessmentRepository, create_database
from job_application_copilot.repositories.models import Assessment, Cv, Job
from job_application_copilot.services import CvReviewNavigation, JobAssessmentDetail, JobService
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.ui.components.job_details import (
    _can_record_application,
    _effective_relevance,
    _render_cv_review_navigation,
    _render_job_details_heading,
    parse_job_id,
    summary_bullets,
)


def test_next_cv_navigation_uses_the_adjacent_review_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Column:
        def __enter__(self) -> "Column":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    class Streamlit:
        def columns(self, _: int) -> tuple[Column, Column]:
            return Column(), Column()

        def page_link(self, *_: object, **__: object) -> None:
            return None

        def button(self, label: str, **_: object) -> bool:
            return label == "Next CV"

        def switch_page(self, _: str, *, query_params: dict[str, str]) -> None:
            destination.update(query_params)

    class Service:
        def review_navigation(self, _: int) -> CvReviewNavigation:
            return CvReviewNavigation(previous_job_id=10, next_job_id=30)

    destination: dict[str, str] = {}
    monkeypatch.setattr("job_application_copilot.ui.components.job_details.st", Streamlit())

    _render_cv_review_navigation(20, Service())  # type: ignore[arg-type]

    assert destination == {"job_id": "30", "tab": "cv"}


@pytest.mark.parametrize("value", [None, "", "abc", "1.5", "0", "-1"])
def test_parse_job_id_rejects_missing_or_invalid_values(value: str | None) -> None:
    with pytest.raises(ValueError):
        parse_job_id(value)


def test_parse_job_id_accepts_positive_integer() -> None:
    assert parse_job_id("42") == 42


def test_job_details_heading_links_the_job_title_to_the_posting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(
        company="Example & Co",
        job_title="Platform <Architect>",
        job_url="https://example.com/job?source=jobs&role=architect",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Lead architecture.",
        date_added=date(2026, 7, 30),
    )
    rendered: dict[str, object] = {}
    monkeypatch.setattr(
        "job_application_copilot.ui.components.job_details.st.markdown",
        lambda *args, **kwargs: rendered.update(text=args[0], **kwargs),
    )

    _render_job_details_heading(job)

    assert rendered["unsafe_allow_html"] is True
    assert (
        rendered["text"]
        == '# Job details — <a href="https://example.com/job?source=jobs&amp;role=architect" '
        'target="_blank" rel="noopener noreferrer">Platform &lt;Architect&gt;</a> (Example &amp; Co)'
    )


def test_job_details_heading_without_url_uses_a_standard_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(
        company="Example Ltd",
        job_title="Platform Architect",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Lead architecture.",
        date_added=date(2026, 7, 30),
    )
    rendered: list[str] = []
    monkeypatch.setattr(
        "job_application_copilot.ui.components.job_details.st.title", rendered.append
    )

    _render_job_details_heading(job)

    assert rendered == ["Job details — Platform Architect (Example Ltd)"]


def test_assessment_detail_returns_current_result_and_detects_staleness(tmp_path) -> None:
    database_path = tmp_path / "assessment-detail.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        with database.session() as session:
            job = Job(
                company="Example Ltd",
                job_title="Architecture Lead",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_description="Lead architecture.",
                date_added=date(2026, 7, 30),
            )
            session.add(job)
            session.flush()
            assessment = Assessment(
                job_id=job.id,
                status=AssessmentStatus.ASSESSED,
                model_relevance=Relevance.HIGH,
                role_snapshot="Lead architecture.",
                real_mandate="Improve delivery.",
                primary_role_family="ARCHITECTURE",
                seniority_fit=8,
                technical_bar="Architecture judgement.",
                tech_bar_fit=7,
                fit_score=8,
                priority_score=7,
                decision="GO",
                decision_reason="Strong evidence.",
                interview_probability_low=5,
                interview_probability_high=7,
                interview_probability_confidence=6,
                recommended_document_b_lane="ARCHITECTURE",
                document_a_version=1,
                prompt_version=2,
                model_name="test-model",
                assessed_at=job.assessment_input_updated_at,
                source_job_updated_at=job.assessment_input_updated_at,
            )
            AssessmentRepository(session).add(assessment)

        service = JobService(database)
        current = service.assessment_detail(job.id)
        assert current.assessment is not None
        assert current.is_stale is False
        assert _effective_relevance(current) == "High"

        with database.session() as session:
            stored_job = session.get(Job, job.id)
            assert stored_job is not None
            stored_job.assessment_input_updated_at = stored_job.assessment_input_updated_at.replace(
                year=2027
            )

        stale = service.assessment_detail(job.id)
        assert stale.is_stale is True
    finally:
        database.dispose()


def test_summary_bullets_normalizes_markers_and_caps_at_ten() -> None:
    source = "\n".join(f"-  Point {number}  " for number in range(12))

    assert summary_bullets(source) == tuple(f"Point {number}" for number in range(10))
    assert summary_bullets("A single summary paragraph.") == ("A single summary paragraph.",)


def test_application_recording_requires_assessment_and_reviewable_cv() -> None:
    job = Job(
        id=1,
        company="Example Ltd",
        job_title="Architecture Lead",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Lead architecture.",
        date_added=date(2026, 7, 30),
    )
    assessment = Assessment(job_id=job.id, status=AssessmentStatus.ASSESSED)
    detail = JobAssessmentDetail(job=job, assessment=assessment, is_stale=False)
    ready_cv = Cv(
        job_id=job.id,
        source=CvSource.UPLOADED,
        status=CvStatus.READY_FOR_REVIEW,
        language=Language.EN,
        file_name="CV.docx",
        file_path="C:/private/cvs/CV.docx",
    )

    assert _can_record_application(detail, ready_cv)
    pending_cv = Cv(
        job_id=job.id,
        source=CvSource.UPLOADED,
        status=CvStatus.PENDING,
        language=Language.EN,
        file_name=None,
        file_path=None,
    )
    assert not _can_record_application(detail, pending_cv)
    assert not _can_record_application(
        JobAssessmentDetail(job=job, assessment=None, is_stale=False), ready_cv
    )
