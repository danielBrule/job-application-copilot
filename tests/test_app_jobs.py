from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    CreateJob,
    CvSelectionStatus,
    CvSource,
    CvStatus,
    DashboardAssessmentStatus,
    DocumentBRoutingSetStatus,
    Language,
    Location,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
    Relevance,
    UserDecision,
)
from job_application_copilot.observability import reset_logging
from job_application_copilot.repositories import AssessmentRepository, BackgroundTaskRepository
from job_application_copilot.repositories.models import (
    Assessment,
    Cv,
    DocumentBLaneRoute,
    DocumentBRoutingSet,
    Job,
    ReferenceAsset,
)
from job_application_copilot.services import (
    JobService,
)
from job_application_copilot.ui.components.job_details import LOAD_ERROR_MESSAGE
from job_application_copilot.ui.components.job_filters import (
    CLEAR_FILTERS_KEY,
    FILTER_APPLICATION_STATUS_KEY,
    FILTER_ASSESSMENT_DECISION_KEY,
    FILTER_ASSESSMENT_STATUS_KEY,
    FILTER_LANGUAGE_KEY,
    FILTER_LOCATION_KEY,
    FILTER_SOURCE_KEY,
    FILTER_TEXT_KEY,
    FILTER_USER_DECISION_KEY,
)
from job_application_copilot.ui.components.job_form import SAVE_ERROR_MESSAGE
from job_application_copilot.ui.components.jobs_dashboard import (
    JOBS_TABLE_KEY,
    SELECTED_JOB_IDS_KEY,
)
from job_application_copilot.ui.components.jobs_dashboard import (
    LOAD_ERROR_MESSAGE as JOBS_LOAD_ERROR_MESSAGE,
)
from job_application_copilot.ui.dependencies import get_database, get_job_service
from tests.app_test_support import APP_PATH


def test_empty_jobs_dashboard_shows_add_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert app.info[0].value == "No jobs have been added yet."
        assert not app.metric
        assert not app.dataframe
        assert not app.button(key="add_job").disabled
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
    finally:
        reset_logging()


def test_jobs_dashboard_displays_core_columns_and_tracks_selected_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        older = service.create(
            CreateJob(
                company="Older Ltd",
                job_title="Data Engineer",
                location=Location.FR,
                language=Language.FR,
                source="Company website",
                job_description="Build data systems.",
                date_added=date(2026, 7, 20),
            )
        )
        newer = _create_job_for_edit(service)
        app.run()

        assert not app.exception
        assert len(app.dataframe) == 1
        table = app.dataframe[0].value
        assert list(table.columns) == [
            "company",
            "job_title",
            "job_url",
            "location",
            "language",
            "source",
            "date_added",
            "assessment_status",
            "recommendation",
            "fit_score",
            "interview_probability",
            "user_decision",
            "selected_cv_lane",
            "cv_selection_status",
            "cv_status",
            "application_status",
            "application_date",
            "next_action",
            "updated_at",
        ]
        assert list(table["company"]) == [
            f"/job-details?job_id={older.id}#Older Ltd",
            f"/job-details?job_id={newer.id}#Original Ltd",
        ]
        assert table["job_url"].iloc[1] == "https://example.com/original"
        assert list(table["assessment_status"]) == ["Not assessed", "Not assessed"]
        assert list(table["cv_selection_status"]) == ["Not selected", "Not selected"]
        assert list(table["cv_status"]) == ["Not available yet", "Not available yet"]
        assert list(table["application_status"]) == ["—", "Interview"]
        assert list(table["next_action"]) == ["—", "Prepare interview"]
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
        add_job = app.button(key="add_job")
        assert not add_job.disabled
        assert all(button.key != "open_selected_job" for button in app.button)

        app.session_state[JOBS_TABLE_KEY] = {"selection": {"rows": [1]}}
        app.run()

        assert app.session_state[SELECTED_JOB_IDS_KEY] == (newer.id,)
        assert any(caption.value == "1 job selected." for caption in app.caption)
        assert all(button.key != "open_selected_job" for button in app.button)
    finally:
        reset_logging()


def test_jobs_dashboard_queues_all_unassessed_jobs_for_assessment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        job = _create_job_for_edit(service)
        app.run()
        app.checkbox(key="confirm_assess_all_unassessed").check().run()
        app.button(key="assess_all_unassessed").click().run()

        assert not app.exception
        assert "Queued 1 unassessed job in batch" in app.success[0].value
        with get_database(database_path).session() as session:
            tasks = BackgroundTaskRepository(session).list(job_id=job.id)
            assert len(tasks) == 1
            assert tasks[0].payload_metadata == {}
    finally:
        reset_logging()


def test_jobs_dashboard_replaces_selection_based_batch_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        _create_job_for_edit(service)
        failed = service.create(
            CreateJob(
                company="Failed Ltd",
                job_title="Platform Engineer",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_description="Build reliable systems.",
                date_added=date(2026, 7, 30),
            )
        )
        with get_database(database_path).session() as session:
            AssessmentRepository(session).add(
                Assessment(
                    job_id=failed.id,
                    status=AssessmentStatus.FAILED,
                    error_message="Timed out.",
                )
            )

        app.run()
        assert app.button(key="assess_all_unassessed")
        assert app.button(key="generate_all_selected_cvs")
        removed_keys = {
            "assess_selected_jobs",
            "reassess_selected_jobs",
            "select_for_cv_generation",
            "generate_selected_cvs",
            "regenerate_selected_cvs",
            "generate_all_pursued_cvs",
        }
        assert not any(button.key in removed_keys for button in app.button)
    finally:
        reset_logging()


def test_jobs_dashboard_links_to_first_assessed_job_awaiting_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        job = _create_job_for_edit(service)
        with get_database(database_path).session() as session:
            stored_job = session.get(Job, job.id)
            assert stored_job is not None
            stored_job.user_decision = UserDecision.UNDECIDED
        _add_assessed_job_with_cv_lanes(database_path, job)

        app.run()

        review_link = next(
            link for link in app.get("page_link") if link.label == "Review assessed jobs"
        )
        assert not review_link.disabled
    finally:
        reset_logging()


def test_jobs_dashboard_queues_all_selected_jobs_for_cv_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        eligible = _create_job_for_edit(service)
        missing_assessment = service.create(
            CreateJob(
                company="Missing assessment Ltd",
                job_title="Platform Engineer",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_description="Build reliable systems.",
                date_added=date(2026, 8, 7),
                user_decision=UserDecision.PURSUE,
            )
        )
        _add_assessed_job_with_cv_lanes(database_path, eligible)
        with get_database(database_path).session() as session:
            stored_job = session.get(Job, eligible.id)
            assessment = AssessmentRepository(session).require_for_job(eligible.id)
            stored_missing_assessment = session.get(Job, missing_assessment.id)
            assert stored_job is not None
            assert stored_missing_assessment is not None
            stored_job.cv_selection_status = CvSelectionStatus.SELECTED
            stored_missing_assessment.cv_selection_status = CvSelectionStatus.SELECTED
            assessment.selected_cv_lane = "ARCHITECTURE"

        app.run()
        app.checkbox(key="confirm_generate_all_selected_cvs").check().run()
        app.button(key="generate_all_selected_cvs").click().run()

        assert not app.exception
        assert "Queued 1 job for CV generation in batch" in app.success[0].value
        assert "missing an assessment" in app.success[0].value
        with get_database(database_path).session() as session:
            tasks = BackgroundTaskRepository(session).list()
            assert len(tasks) == 1
            assert tasks[0].job_id == eligible.id
            assert tasks[0].operation.value == "CV_GENERATION"
        assert missing_assessment.id not in [task.job_id for task in tasks]
    finally:
        reset_logging()


def test_jobs_dashboard_queues_selected_generated_cv_for_regeneration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        job = _create_job_for_edit(service)
        _add_assessed_job_with_cv_lanes(database_path, job)
        with get_database(database_path).session() as session:
            stored_job = session.get(Job, job.id)
            assessment = AssessmentRepository(session).require_for_job(job.id)
            assert stored_job is not None
            stored_job.cv_selection_status = CvSelectionStatus.SELECTED
            assessment.selected_cv_lane = "ARCHITECTURE"
            session.add(
                Cv(
                    job_id=job.id,
                    source=CvSource.GENERATED,
                    status=CvStatus.READY_FOR_REVIEW,
                    language=Language.EN,
                    file_name="prior.docx",
                    file_path="C:/private/cvs/prior.docx",
                )
            )

        app.session_state[JOBS_TABLE_KEY] = {"selection": {"rows": [0]}}
        app.run()
        app.checkbox(key="confirm_regenerate_selected_cvs").check().run()
        app.button(key="regenerate_selected_cvs").click().run()

        assert not app.exception
        assert "Queued 1 job for CV regeneration in batch" in app.success[0].value
        with get_database(database_path).session() as session:
            tasks = BackgroundTaskRepository(session).list(job_id=job.id)
            assert len(tasks) == 1
            assert tasks[0].payload_metadata == {}
    finally:
        reset_logging()


def test_jobs_dashboard_combines_filters_clears_selection_and_resets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        service.create(
            CreateJob(
                company="Another Ltd",
                job_title="Data Engineer",
                location=Location.FR,
                language=Language.FR,
                source="Company website",
                job_description="Build data systems.",
                date_added=date(2026, 7, 20),
                application_status="Not applied",
            )
        )
        matching_job = _create_job_for_edit(service)
        app.run()

        assert app.selectbox(key=FILTER_SOURCE_KEY).options == [
            "All",
            "Company website",
            "LinkedIn",
        ]

        app.session_state[JOBS_TABLE_KEY] = {"selection": {"rows": [1]}}
        app.run()
        assert app.session_state[SELECTED_JOB_IDS_KEY] == (matching_job.id,)

        app.text_input(key=FILTER_TEXT_KEY).input(" original ").run()
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
        assert [value.rsplit("#", 1)[-1] for value in app.dataframe[0].value["company"]] == [
            "Original Ltd"
        ]

        app.selectbox(key=FILTER_LOCATION_KEY).select(Location.UK).run()
        app.selectbox(key=FILTER_LANGUAGE_KEY).select(Language.EN).run()
        app.selectbox(key=FILTER_SOURCE_KEY).select("LinkedIn").run()
        app.selectbox(key=FILTER_USER_DECISION_KEY).select(UserDecision.PURSUE).run()
        app.text_input(key=FILTER_APPLICATION_STATUS_KEY).input("VIEW").run()
        app.selectbox(key=FILTER_ASSESSMENT_STATUS_KEY).select(
            DashboardAssessmentStatus.NOT_ASSESSED
        ).run()

        assert not app.exception
        assert [value.rsplit("#", 1)[-1] for value in app.dataframe[0].value["company"]] == [
            "Original Ltd"
        ]

        app.selectbox(key=FILTER_LOCATION_KEY).select(Location.FR).run()

        assert not app.dataframe
        assert app.info[0].value == "No jobs match the current filters."
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()

        app.button(key=CLEAR_FILTERS_KEY).click().run()

        assert app.text_input(key=FILTER_TEXT_KEY).value == ""
        assert app.selectbox(key=FILTER_LOCATION_KEY).value is None
        assert app.selectbox(key=FILTER_LANGUAGE_KEY).value is None
        assert app.selectbox(key=FILTER_SOURCE_KEY).value is None
        assert app.selectbox(key=FILTER_USER_DECISION_KEY).value is None
        assert app.text_input(key=FILTER_APPLICATION_STATUS_KEY).value == ""
        assert app.selectbox(key=FILTER_ASSESSMENT_STATUS_KEY).value is None
        assert app.selectbox(key=FILTER_ASSESSMENT_DECISION_KEY).value is None
        assert [value.rsplit("#", 1)[-1] for value in app.dataframe[0].value["company"]] == [
            "Another Ltd",
            "Original Ltd",
        ]
        assert len(service.list()) == 2
    finally:
        reset_logging()


def test_jobs_dashboard_database_failure_shows_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    def fail_list(self: JobService, filters: object = None) -> None:
        del self, filters
        from sqlalchemy.exc import OperationalError

        raise OperationalError("SELECT", {}, RuntimeError("private database detail"))

    monkeypatch.setattr(JobService, "list", fail_list)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.error[0].value == JOBS_LOAD_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
    finally:
        reset_logging()


def test_add_job_form_uses_configured_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAC_DEFAULT_SOURCE", "Company website")
    monkeypatch.setenv("JAC_DEFAULT_LOCATION", "FR")
    monkeypatch.setenv("JAC_DEFAULT_LANGUAGE", "FR")
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        app.switch_page("pages/add_job.py").run()

        assert not app.exception
        assert app.title[0].value == "Add job"
        assert app.text_input(key="add_job_0_source").value == "Company website"
        assert app.selectbox(key="add_job_0_location").value == "FR"
        assert app.selectbox(key="add_job_0_language").value == "FR"
        assert "add_job_0_relevance_override" not in {selectbox.key for selectbox in app.selectbox}
        assert app.date_input(key="add_job_0_date_added").value == date.today()
    finally:
        reset_logging()


def test_valid_add_job_submission_persists_and_returns_to_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        app.switch_page("pages/add_job.py").run()
        app.text_input(key="add_job_0_company").input("Example Ltd")
        app.text_input(key="add_job_0_job_title").input("Platform Engineer")
        app.text_input(key="add_job_0_job_url").input("https://example.com/job")
        app.text_area(key="add_job_0_job_description").input("Build and operate reliable systems.")
        app.text_area(key="add_job_0_general_notes").input("Initial note")
        app.button(key="FormSubmitter:add_job_0_form-Save").click().run()

        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert app.success[0].value == "Saved Example Ltd — Platform Engineer."

        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        jobs = service.list()
        assert len(jobs) == 1
        assert jobs[0].company == "Example Ltd"
        assert jobs[0].job_title == "Platform Engineer"
        assert jobs[0].source == "LinkedIn"
        assert jobs[0].date_added == date.today()
        assert jobs[0].relevance_override is None
    finally:
        reset_logging()


def test_missing_required_add_job_fields_show_errors_without_saving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        app.switch_page("pages/add_job.py").run()
        app.button(key="FormSubmitter:add_job_0_form-Save").click().run()

        assert not app.exception
        assert [error.value for error in app.error] == [
            "Company is required.",
            "Job title is required.",
            "Full job description is required.",
        ]
        assert get_job_service(data_dir / "database" / "job_application_copilot.db").list() == []
    finally:
        reset_logging()


def test_duplicate_job_url_shows_useful_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        app.switch_page("pages/add_job.py").run()
        _fill_required_add_job_fields(app, company="First")
        app.text_input(key="add_job_0_job_url").input("https://example.com/job")
        app.button(key="FormSubmitter:add_job_0_form-Save and add another").click().run()

        _fill_required_add_job_fields(app, company="Duplicate", version=1)
        app.text_input(key="add_job_1_job_url").input("https://example.com/job")
        app.button(key="FormSubmitter:add_job_1_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == "Another job already uses this exact URL (job 1)."
        assert (
            len(get_job_service(data_dir / "database" / "job_application_copilot.db").list()) == 1
        )
    finally:
        reset_logging()


def test_cancel_add_job_returns_to_jobs_without_saving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        app.switch_page("pages/add_job.py").run()
        _fill_required_add_job_fields(app)
        app.button(key="FormSubmitter:add_job_0_form-Cancel").click().run()

        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert get_job_service(data_dir / "database" / "job_application_copilot.db").list() == []
    finally:
        reset_logging()


def test_database_failure_shows_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    def fail_create(self: JobService, command: object) -> None:
        del self, command
        from sqlalchemy.exc import OperationalError

        raise OperationalError("INSERT", {}, RuntimeError("private database detail"))

    try:
        app.switch_page("pages/add_job.py").run()
        _fill_required_add_job_fields(app)
        monkeypatch.setattr(JobService, "create", fail_create)
        app.button(key="FormSubmitter:add_job_0_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == SAVE_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
    finally:
        reset_logging()


def _fill_required_add_job_fields(
    app: AppTest,
    company: str = "Example Ltd",
    version: int = 0,
) -> None:
    app.text_input(key=f"add_job_{version}_company").input(company)
    app.text_input(key=f"add_job_{version}_job_title").input("Platform Engineer")
    app.text_area(key=f"add_job_{version}_job_description").input(
        "Build and operate reliable systems."
    )


def test_job_details_form_loads_existing_values_and_persists_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        job = _create_job_for_edit(service)
        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()

        assert not app.exception
        assert any(
            "Original title" in markdown.value and "Original Ltd" in markdown.value
            for markdown in app.markdown
        )
        assert app.subheader[0].value == "Edit job"
        assert app.text_input(key=f"edit_job_{job.id}_company").value == "Original Ltd"
        assert app.text_input(key=f"edit_job_{job.id}_job_title").value == "Original title"
        assert app.selectbox(key=f"edit_job_{job.id}_location").value == "UK"
        assert app.selectbox(key=f"edit_job_{job.id}_language").value == "EN"
        assert app.selectbox(key=f"edit_job_{job.id}_relevance_override").value is None
        assert app.text_input(key=f"edit_job_{job.id}_source").value == "LinkedIn"
        assert (
            app.text_input(key=f"edit_job_{job.id}_job_url").value == "https://example.com/original"
        )
        assert (
            app.text_area(key=f"edit_job_{job.id}_job_description").value == "Original description"
        )
        assert app.date_input(key=f"edit_job_{job.id}_date_added").value == date(2026, 7, 1)
        assert app.text_area(key=f"edit_job_{job.id}_general_notes").value == "Original notes"

        app.text_input(key=f"edit_job_{job.id}_company").input("Updated Ltd")
        app.text_input(key=f"edit_job_{job.id}_job_title").input("Updated title")
        app.selectbox(key=f"edit_job_{job.id}_location").select("FR")
        app.selectbox(key=f"edit_job_{job.id}_language").select("FR")
        app.selectbox(key=f"edit_job_{job.id}_relevance_override").select(Relevance.MEDIUM)
        app.text_input(key=f"edit_job_{job.id}_source").input("Company website")
        app.text_input(key=f"edit_job_{job.id}_job_url").input("https://example.com/updated")
        app.text_area(key=f"edit_job_{job.id}_job_description").input("Updated description")
        app.date_input(key=f"edit_job_{job.id}_date_added").set_value(date(2026, 7, 20))
        app.text_area(key=f"edit_job_{job.id}_general_notes").input("Updated notes")
        app.button(key=f"FormSubmitter:edit_job_{job.id}_form-Save").click().run()

        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert app.success[0].value == "Saved Updated Ltd — Updated title."
        updated = service.get(job.id)
        assert updated is not None
        assert updated.company == "Updated Ltd"
        assert updated.job_title == "Updated title"
        assert updated.location is Location.FR
        assert updated.language is Language.FR
        assert updated.relevance_override is Relevance.MEDIUM
        assert updated.source == "Company website"
        assert updated.job_url == "https://example.com/updated"
        assert updated.job_description == "Updated description"
        assert updated.date_added == date(2026, 7, 20)
        assert updated.general_notes == "Updated notes"
        assert updated.user_decision is UserDecision.PURSUE
        assert updated.application_status == "Interview"
        assert updated.next_action == "Prepare interview"
    finally:
        reset_logging()


def test_cancel_job_edit_returns_to_jobs_without_updating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        job = _create_job_for_edit(service)
        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()
        app.text_input(key=f"edit_job_{job.id}_company").input("Must not persist")
        app.button(key=f"FormSubmitter:edit_job_{job.id}_form-Cancel").click().run()

        assert not app.exception
        assert app.title[0].value == "Jobs"
        stored = service.get(job.id)
        assert stored is not None
        assert stored.company == "Original Ltd"
    finally:
        reset_logging()


@pytest.mark.parametrize(
    ("job_id", "expected_message"),
    [
        (None, "A job ID is required."),
        ("abc", "The job ID must be a positive integer."),
        ("0", "The job ID must be a positive integer."),
        ("999", "Job 999 does not exist."),
    ],
)
def test_job_details_rejects_missing_invalid_or_unknown_job_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_id: str | None,
    expected_message: str,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        if job_id is not None:
            app.query_params["job_id"] = job_id
        app.switch_page("pages/job_details.py").run()

        assert not app.exception
        assert app.error[0].value == expected_message
        assert not app.subheader
    finally:
        reset_logging()


def test_job_edit_rejects_another_jobs_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        first = _create_job_for_edit(service)
        second = service.create(
            CreateJob(
                company="Second Ltd",
                job_title="Second title",
                location=Location.FR,
                language=Language.FR,
                source="Company website",
                job_url="https://example.com/second",
                job_description="Second description",
                date_added=date(2026, 7, 2),
            )
        )
        app.query_params["job_id"] = str(second.id)
        app.switch_page("pages/job_details.py").run()
        app.text_input(key=f"edit_job_{second.id}_job_url").input(first.job_url or "")
        app.button(key=f"FormSubmitter:edit_job_{second.id}_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == f"Another job already uses this exact URL (job {first.id})."
        stored = service.get(second.id)
        assert stored is not None
        assert stored.job_url == "https://example.com/second"
    finally:
        reset_logging()


def test_job_load_database_failure_shows_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    def fail_get(self: JobService, job_id: int) -> None:
        del self, job_id
        from sqlalchemy.exc import OperationalError

        raise OperationalError("SELECT", {}, RuntimeError("private database detail"))

    try:
        monkeypatch.setattr(JobService, "assessment_detail", fail_get)
        app.query_params["job_id"] = "1"
        app.switch_page("pages/job_details.py").run()

        assert not app.exception
        assert app.error[0].value == LOAD_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
    finally:
        reset_logging()


def test_job_details_assessment_tab_displays_assessed_handover_and_stale_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        job = _create_job_for_edit(service)
        with get_database(database_path).session() as session:
            AssessmentRepository(session).add(
                Assessment(
                    job_id=job.id,
                    status=AssessmentStatus.ASSESSED,
                    model_relevance=Relevance.HIGH,
                    role_snapshot="Lead platform architecture.",
                    real_mandate="Improve engineering delivery.",
                    primary_role_family="ARCHITECTURE",
                    secondary_role_family="AI_DEPLOYMENT",
                    seniority_fit=8,
                    technical_bar="Strong architecture judgement.",
                    tech_bar_fit=8,
                    fit_score=8,
                    priority_score=7,
                    decision=AssessmentDecision.GO,
                    decision_reason="Evidence supports the mandate.",
                    interview_probability_low=5,
                    interview_probability_high=7,
                    interview_probability_confidence=6,
                    strong_fit_signals=["Architecture leadership"],
                    red_flags=[],
                    sustainability_risks=["Operational escalation"],
                    evidence_gaps=["No industry evidence"],
                    evidence_anchors=[
                        {
                            "source_reference": "A-01",
                            "evidence": "Led a shared workstream.",
                            "supports": "Architecture credibility.",
                        }
                    ],
                    evidence_confidence=8,
                    recommended_document_b_lane="ARCHITECTURE",
                    secondary_cv_angle="Delivery transformation",
                    overclaiming_risks=["Do not claim sole ownership."],
                    document_a_version=3,
                    prompt_version=4,
                    model_name="test-model",
                    assessed_at=job.assessment_input_updated_at,
                    source_job_updated_at=job.assessment_input_updated_at,
                )
            )
            stored_job = session.get(Job, job.id)
            assert stored_job is not None
            stored_job.assessment_input_updated_at = stored_job.assessment_input_updated_at.replace(
                year=2027
            )

        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()

        assert not app.exception
        assert [tab.label for tab in app.tabs] == ["Job", "Assessment", "CV"]
        assert any("This assessment is stale" in warning.value for warning in app.warning)
        assert any(
            metric.label == "Model relevance" and metric.value == "High" for metric in app.metric
        )
        assert any("ARCHITECTURE" in markdown.value for markdown in app.markdown)
        assert list(app.dataframe[0].value["source_reference"]) == ["A-01"]
    finally:
        reset_logging()


def test_job_details_saves_human_decision_and_notes_without_changing_model_recommendation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        job = _create_job_for_edit(service)
        with get_database(database_path).session() as session:
            AssessmentRepository(session).add(
                Assessment(
                    job_id=job.id,
                    status=AssessmentStatus.ASSESSED,
                    model_relevance=Relevance.HIGH,
                    role_snapshot="Lead platform architecture.",
                    real_mandate="Improve engineering delivery.",
                    primary_role_family="ARCHITECTURE",
                    seniority_fit=8,
                    technical_bar="Strong architecture judgement.",
                    fit_score=8,
                    priority_score=7,
                    decision=AssessmentDecision.GO,
                    decision_reason="Evidence supports the mandate.",
                    recommended_document_b_lane="ARCHITECTURE",
                    assessed_at=job.assessment_input_updated_at,
                    source_job_updated_at=job.assessment_input_updated_at,
                )
            )

        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()
        decision = next(select for select in app.selectbox if select.label == "Decision")
        assert decision.disabled

        assert not app.exception
        detail = service.assessment_detail(job.id)
        assert detail.job.user_decision is UserDecision.PURSUE
        assert detail.assessment is not None
        assert detail.assessment.assessment_notes is None
        assert detail.assessment.decision is AssessmentDecision.GO
        assert any(
            metric.label == "Recommendation" and metric.value == "Go" for metric in app.metric
        )
    finally:
        reset_logging()


def test_job_details_defaults_and_persists_selected_cv_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        job = _create_job_for_edit(service)
        _add_assessed_job_with_cv_lanes(database_path, job)

        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()
        selected_lane = next(
            select for select in app.selectbox if select.label == "Selected CV lane"
        )
        assert selected_lane.value == "ARCHITECTURE"
        assert selected_lane.options == ["AI_DEPLOYMENT", "ARCHITECTURE"]

        selected_lane.select("AI_DEPLOYMENT").run()
        app.button(
            key=f"FormSubmitter:human_review_{job.id}_form-Save review details"
        ).click().run()

        detail = service.assessment_detail(job.id)
        assert detail.assessment is not None
        assert detail.assessment.selected_cv_lane == "AI_DEPLOYMENT"
        assert detail.assessment.recommended_document_b_lane == "ARCHITECTURE"

        app.switch_page("pages/job_details.py").run()
        selected_lane = next(
            select for select in app.selectbox if select.label == "Selected CV lane"
        )
        assert selected_lane.value == "AI_DEPLOYMENT"
    finally:
        reset_logging()


def test_review_decision_keeps_next_assessed_job_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        database_path = data_dir / "database" / "job_application_copilot.db"
        service = get_job_service(database_path)
        next_job = _create_job_for_edit(service)
        intermediate_job = service.create(
            CreateJob(
                company="Intermediate Ltd",
                job_title="Intermediate role",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_url="https://example.com/intermediate",
                job_description="Intermediate description.",
                date_added=date(2026, 7, 2),
            )
        )
        current_job = service.create(
            CreateJob(
                company="Current Ltd",
                job_title="Current role",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_url="https://example.com/current",
                job_description="Current description.",
                date_added=date(2026, 7, 3),
            )
        )
        _add_assessed_job_with_cv_lanes(database_path, next_job)
        with get_database(database_path).session() as session:
            stored_next_job = session.get(Job, next_job.id)
            stored_current_job = session.get(Job, current_job.id)
            assert stored_next_job is not None
            assert stored_current_job is not None
            stored_next_job.user_decision = UserDecision.UNDECIDED
            stored_current_job.user_decision = UserDecision.UNDECIDED
            session.add(
                Assessment(
                    job_id=intermediate_job.id,
                    status=AssessmentStatus.ASSESSED,
                    model_relevance=Relevance.HIGH,
                    role_snapshot="Intermediate role snapshot.",
                    real_mandate="Intermediate mandate.",
                    primary_role_family="ARCHITECTURE",
                    seniority_fit=8,
                    technical_bar="Architecture judgement.",
                    fit_score=8,
                    priority_score=7,
                    decision=AssessmentDecision.GO,
                    decision_reason="Strong evidence supports the mandate.",
                    recommended_document_b_lane="ARCHITECTURE",
                    assessed_at=intermediate_job.assessment_input_updated_at,
                    source_job_updated_at=intermediate_job.assessment_input_updated_at,
                )
            )
            session.add(
                Assessment(
                    job_id=current_job.id,
                    status=AssessmentStatus.ASSESSED,
                    model_relevance=Relevance.HIGH,
                    role_snapshot="Current role snapshot.",
                    real_mandate="Current mandate.",
                    primary_role_family="ARCHITECTURE",
                    seniority_fit=8,
                    technical_bar="Architecture judgement.",
                    fit_score=8,
                    priority_score=7,
                    decision=AssessmentDecision.GO,
                    decision_reason="Strong evidence supports the mandate.",
                    recommended_document_b_lane="ARCHITECTURE",
                    assessed_at=current_job.assessment_input_updated_at,
                    source_job_updated_at=current_job.assessment_input_updated_at,
                )
            )

        app.query_params["job_id"] = str(current_job.id)
        app.switch_page("pages/job_details.py").run()
        app.selectbox(key=f"human_review_decision_{current_job.id}").select(
            UserDecision.DO_NOT_PURSUE
        ).run()

        assert not app.exception
        assert (
            service.assessment_detail(current_job.id).job.user_decision
            is UserDecision.DO_NOT_PURSUE
        )
        app.button(key=f"next_assessment_review_{current_job.id}").click().run()
        app.selectbox(key=f"human_review_decision_{intermediate_job.id}").select(
            UserDecision.DO_NOT_PURSUE
        ).run()

        assert (
            service.assessment_detail(intermediate_job.id).job.user_decision
            is UserDecision.DO_NOT_PURSUE
        )
        app.button(key=f"next_assessment_review_{intermediate_job.id}").click().run()
        app.selectbox(key=f"human_review_decision_{next_job.id}").select(
            UserDecision.DO_NOT_PURSUE
        ).run()

        assert (
            service.assessment_detail(next_job.id).job.user_decision is UserDecision.DO_NOT_PURSUE
        )
        assert app.button(key=f"next_assessment_review_{next_job.id}").disabled
    finally:
        reset_logging()


def test_job_deleted_before_save_rerun_shows_useful_load_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        job = _create_job_for_edit(service)
        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()
        service.delete(job.id)
        app.button(key=f"FormSubmitter:edit_job_{job.id}_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == f"Job {job.id} does not exist."
    finally:
        reset_logging()


def test_job_update_database_failure_shows_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    def fail_update(self: JobService, job_id: int, command: object) -> None:
        del self, job_id, command
        from sqlalchemy.exc import OperationalError

        raise OperationalError("UPDATE", {}, RuntimeError("private database detail"))

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        job = _create_job_for_edit(service)
        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()
        monkeypatch.setattr(JobService, "update", fail_update)
        app.button(key=f"FormSubmitter:edit_job_{job.id}_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == SAVE_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
    finally:
        reset_logging()


def _create_job_for_edit(service: JobService) -> Job:
    return service.create(
        CreateJob(
            company="Original Ltd",
            job_title="Original title",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_url="https://example.com/original",
            job_description="Original description",
            date_added=date(2026, 7, 1),
            general_notes="Original notes",
            user_decision=UserDecision.PURSUE,
            application_status="Interview",
            application_date=date(2026, 7, 10),
            next_action="Prepare interview",
            next_action_date=date(2026, 7, 30),
            salary_expectation="GBP 150,000",
        )
    )


def _add_assessed_job_with_cv_lanes(database_path: Path, job: Job) -> None:
    with get_database(database_path).session() as session:
        session.add(
            Assessment(
                job_id=job.id,
                status=AssessmentStatus.ASSESSED,
                model_relevance=Relevance.HIGH,
                role_snapshot="Lead platform architecture.",
                real_mandate="Improve engineering delivery.",
                primary_role_family="ARCHITECTURE",
                seniority_fit=8,
                technical_bar="Strong architecture judgement.",
                fit_score=8,
                priority_score=7,
                decision=AssessmentDecision.GO,
                decision_reason="Evidence supports the mandate.",
                recommended_document_b_lane="ARCHITECTURE",
                assessed_at=job.assessment_input_updated_at,
                source_job_updated_at=job.assessment_input_updated_at,
            )
        )
        document_b = ReferenceAsset(
            asset_key="document-b",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document B",
            version=1,
            file_path="document_b/document-b-v0001.docx",
            file_hash="sha256:" + ("b" * 64),
            is_active=True,
            processing_status=ReferenceAssetProcessingStatus.READY,
        )
        session.add(document_b)
        session.flush()
        routing_set = DocumentBRoutingSet(
            reference_asset_id=document_b.id,
            routing_config_version="routing-v1",
            routing_config_sha256="sha256:" + ("c" * 64),
            document_b_file_sha256="sha256:" + ("b" * 64),
            extracted_section_catalog_sha256="sha256:" + ("d" * 64),
            status=DocumentBRoutingSetStatus.VALIDATED,
            is_current=True,
        )
        session.add(routing_set)
        session.flush()
        session.add_all(
            [
                DocumentBLaneRoute(
                    routing_set_id=routing_set.id,
                    lane_id=lane,
                    ordered_route_json="{}",
                    secondary_lane_constraints_json="{}",
                )
                for lane in ("ARCHITECTURE", "AI_DEPLOYMENT")
            ]
        )
