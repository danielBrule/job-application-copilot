from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from sqlalchemy import inspect
from streamlit.testing.v1 import AppTest

from job_application_copilot.domain import CreateJob, Language, Location, UserDecision
from job_application_copilot.observability import reset_logging
from job_application_copilot.repositories import create_database
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import JobService
from job_application_copilot.ui.app import UNEXPECTED_ERROR_MESSAGE
from job_application_copilot.ui.dependencies import get_database, get_job_service
from job_application_copilot.ui.job_details import LOAD_ERROR_MESSAGE
from job_application_copilot.ui.job_filters import (
    CLEAR_FILTERS_KEY,
    FILTER_APPLICATION_STATUS_KEY,
    FILTER_LANGUAGE_KEY,
    FILTER_LOCATION_KEY,
    FILTER_SOURCE_KEY,
    FILTER_TEXT_KEY,
    FILTER_USER_DECISION_KEY,
)
from job_application_copilot.ui.job_form import SAVE_ERROR_MESSAGE
from job_application_copilot.ui.jobs_dashboard import (
    JOBS_TABLE_KEY,
    SELECTED_JOB_IDS_KEY,
)
from job_application_copilot.ui.jobs_dashboard import (
    LOAD_ERROR_MESSAGE as JOBS_LOAD_ERROR_MESSAGE,
)

APP_PATH = Path(__file__).parents[1] / "src" / "job_application_copilot" / "ui" / "app.py"


@pytest.fixture(autouse=True)
def clear_ui_database_cache() -> None:
    get_database.clear()
    yield
    get_database.clear()


def test_streamlit_app_starts_and_creates_private_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert (data_dir / "database").is_dir()
        assert (data_dir / "cvs").is_dir()
        assert (data_dir / "logs").is_dir()
        assert (data_dir / "reference" / "document_a").is_dir()
        assert (data_dir / "reference" / "document_b").is_dir()
        assert (data_dir / "reference" / "templates").is_dir()
        assert (data_dir / "reference" / "examples").is_dir()
        assert (data_dir / "reference" / "prompts" / "assessment").is_dir()
        assert (data_dir / "reference" / "prompts" / "generation" / "english").is_dir()
        assert (data_dir / "reference" / "prompts" / "generation" / "french").is_dir()
        log_contents = (data_dir / "logs" / "ui.log").read_text(encoding="utf-8")
        assert "application_started" in log_contents
        database_path = data_dir / "database" / "job_application_copilot.db"
        database = create_database(database_path)
        try:
            assert inspect(database.engine).get_table_names() == [
                "alembic_version",
                "jobs",
            ]
        finally:
            database.dispose()
    finally:
        reset_logging()


@pytest.mark.parametrize(
    ("page_path", "expected_title", "expected_message"),
    [
        (
            "pages/background_runs.py",
            "Background Runs",
            "Background task monitoring will be implemented in milestone M4.",
        ),
        (
            "pages/settings.py",
            "Settings",
            "Reference asset management will be implemented in milestone M3.",
        ),
    ],
)
def test_navigation_reaches_each_primary_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page_path: str,
    expected_title: str,
    expected_message: str,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        app.switch_page(page_path).run()

        assert not app.exception
        assert app.title[0].value == expected_title
        assert app.info[0].value == expected_message
    finally:
        reset_logging()


def test_empty_jobs_dashboard_shows_add_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert app.info[0].value == "No jobs have been added yet."
        assert not app.dataframe
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
        service.create(
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
            "updated_at",
        ]
        assert list(table["company"]) == ["Older Ltd", "Original Ltd"]
        assert table["job_url"].iloc[1] == "https://example.com/original"
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
        assert app.get("page_link")[-1].disabled

        app.session_state[JOBS_TABLE_KEY] = {"selection": {"rows": [1]}}
        app.run()

        assert app.session_state[SELECTED_JOB_IDS_KEY] == (newer.id,)
        assert app.caption[0].value == "1 job selected."
        open_selected_job = app.get("page_link")[-1]
        assert not open_selected_job.disabled
        assert open_selected_job.label == "Open selected job"
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
        assert list(app.dataframe[0].value["company"]) == ["Original Ltd"]

        app.selectbox(key=FILTER_LOCATION_KEY).select(Location.UK).run()
        app.selectbox(key=FILTER_LANGUAGE_KEY).select(Language.EN).run()
        app.selectbox(key=FILTER_SOURCE_KEY).select("LinkedIn").run()
        app.selectbox(key=FILTER_USER_DECISION_KEY).select(UserDecision.PURSUE).run()
        app.text_input(key=FILTER_APPLICATION_STATUS_KEY).input("VIEW").run()

        assert not app.exception
        assert list(app.dataframe[0].value["company"]) == ["Original Ltd"]

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
        assert list(app.dataframe[0].value["company"]) == [
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

    app = AppTest.from_file(str(APP_PATH)).run()

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
    app = AppTest.from_file(str(APP_PATH)).run()

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
        assert app.title[0].value == "Job details"
        assert app.subheader[0].value == "Edit job"
        assert app.text_input(key=f"edit_job_{job.id}_company").value == "Original Ltd"
        assert app.text_input(key=f"edit_job_{job.id}_job_title").value == "Original title"
        assert app.selectbox(key=f"edit_job_{job.id}_location").value == "UK"
        assert app.selectbox(key=f"edit_job_{job.id}_language").value == "EN"
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
        assert app.title[0].value == "Job details"
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
        monkeypatch.setattr(JobService, "get", fail_get)
        app.query_params["job_id"] = "1"
        app.switch_page("pages/job_details.py").run()

        assert not app.exception
        assert app.error[0].value == LOAD_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
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


def test_invalid_settings_stop_before_page_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAC_ASSESSMENT_WORKER_COUNT", "6")
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.error
        assert "less than or equal to 5" in app.error[0].value
        assert not app.title
    finally:
        reset_logging()


def test_unexpected_page_error_is_logged_and_hidden_from_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingPage:
        def run(self) -> None:
            raise RuntimeError("private failure detail")

    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(st, "navigation", lambda pages: FailingPage())
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.error[0].value == UNEXPECTED_ERROR_MESSAGE
        assert "private failure detail" not in app.error[0].value
        log_contents = (tmp_path / "data" / "logs" / "ui.log").read_text(encoding="utf-8")
        assert "unexpected_page_error" in log_contents
        assert "RuntimeError" in log_contents
    finally:
        reset_logging()
