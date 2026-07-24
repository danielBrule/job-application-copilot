from pathlib import Path

import pytest
import streamlit as st
from sqlalchemy import inspect
from streamlit.testing.v1 import AppTest

from job_application_copilot.observability import reset_logging
from job_application_copilot.repositories import create_database
from job_application_copilot.ui.app import UNEXPECTED_ERROR_MESSAGE

APP_PATH = Path(__file__).parents[1] / "src" / "job_application_copilot" / "ui" / "app.py"


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
            "Job management will be implemented in milestone M2.",
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
def test_navigation_reaches_each_empty_page(
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
