from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from sqlalchemy import inspect
from streamlit.testing.v1 import AppTest

from job_application_copilot.observability import reset_logging
from job_application_copilot.repositories import create_database
from job_application_copilot.services import JobService
from job_application_copilot.ui.app import UNEXPECTED_ERROR_MESSAGE
from job_application_copilot.ui.dependencies import get_database, get_job_service
from job_application_copilot.ui.job_form import SAVE_ERROR_MESSAGE

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
            "pages/jobs.py",
            "Jobs",
            "The jobs dashboard table will be implemented in T2.5.",
        ),
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
