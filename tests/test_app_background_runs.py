"""Streamlit behavior tests for the Background Runs screen."""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundTaskStatus,
    Language,
    Location,
)
from job_application_copilot.observability import reset_logging
from job_application_copilot.repositories import (
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    create_database,
)
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask, Job
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.ui.components.background_runs import (
    BACKGROUND_RUNS_TABLE_KEY,
    FILTER_BATCH_KEY,
    FILTER_JOB_KEY,
    FILTER_OPERATION_KEY,
    FILTER_STATUS_KEY,
    INCLUDE_COMPLETED_KEY,
    REFRESH_BUTTON_KEY,
    RETRY_ALL_CONFIRMATION_KEY,
)
from tests.app_test_support import APP_PATH


def seed_failed_task(database_path: Path) -> int:
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        with database.session() as session:
            job = Job(
                company="Example Ltd",
                job_title="Platform Engineer",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_description="Build reliable systems.",
                date_added=date(2026, 7, 29),
            )
            session.add(job)
            session.flush()
            batch = BackgroundBatchRepository(session).add(
                BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
            )
            task = BackgroundTaskRepository(session).add(
                BackgroundTask(
                    batch_id=batch.id,
                    job_id=job.id,
                    operation=BackgroundOperation.ASSESSMENT,
                )
            )
            BackgroundTaskRepository(session).transition(task, BackgroundTaskStatus.RUNNING)
            BackgroundTaskRepository(session).transition(
                task,
                BackgroundTaskStatus.FAILED,
                error_message="Visible local task error.",
            )
            return task.id
    finally:
        database.dispose()


def seed_completed_task(database_path: Path) -> int:
    database = create_database(database_path)
    try:
        with database.session() as session:
            job = Job(
                company="Completed Ltd",
                job_title="Platform Engineer",
                location=Location.UK,
                language=Language.EN,
                source="LinkedIn",
                job_description="Build reliable systems.",
                date_added=date(2026, 7, 29),
            )
            session.add(job)
            session.flush()
            batch = BackgroundBatchRepository(session).add(
                BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
            )
            task = BackgroundTaskRepository(session).add(
                BackgroundTask(
                    batch_id=batch.id,
                    job_id=job.id,
                    operation=BackgroundOperation.ASSESSMENT,
                )
            )
            BackgroundTaskRepository(session).transition(task, BackgroundTaskStatus.RUNNING)
            BackgroundTaskRepository(session).transition(task, BackgroundTaskStatus.COMPLETED)
            return task.id
    finally:
        database.dispose()


def test_background_runs_filters_history_and_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    database_path = data_dir / "database" / "job_application_copilot.db"
    database_path.parent.mkdir(parents=True)
    task_id = seed_failed_task(database_path)
    seed_completed_task(database_path)
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    try:
        app.switch_page("pages/background_runs.py").run()

        assert not app.exception
        assert app.title[0].value == "Background Runs"
        assert app.button(key=REFRESH_BUTTON_KEY)
        assert app.selectbox(key=FILTER_OPERATION_KEY).options == [
            "All operations",
            "ASSESSMENT",
            "CV_GENERATION",
        ]
        assert app.selectbox(key=FILTER_STATUS_KEY).options == [
            "All statuses",
            "PENDING",
            "RUNNING",
            "COMPLETED",
            "FAILED",
            "INTERRUPTED",
        ]
        assert len(app.selectbox(key=FILTER_BATCH_KEY).options) == 2
        assert len(app.selectbox(key=FILTER_JOB_KEY).options) == 2
        assert app.checkbox(key=INCLUDE_COMPLETED_KEY).value is False
        table = app.dataframe[0].value
        assert list(table.columns) == [
            "batch",
            "job",
            "operation",
            "status",
            "pipeline_step",
            "started",
            "completed",
            "duration",
            "error",
        ]
        assert list(table["job"]) == ["Example Ltd — Platform Engineer"]
        assert list(table["error"]) == ["Error"]

        app.session_state[BACKGROUND_RUNS_TABLE_KEY] = {"selection": {"rows": [0]}}
        app.run()

        assert any(expander.label == f"Task {task_id} details" for expander in app.expander)
        assert any(error.value == "Visible local task error." for error in app.error)
        assert any("Attempt history (1)" in markdown.value for markdown in app.markdown)
        assert app.button(key=f"background_run_retry_{task_id}")

        app.checkbox(key=INCLUDE_COMPLETED_KEY).set_value(True).run()

        assert not app.exception
        table = app.dataframe[0].value
        assert "Completed Ltd — Platform Engineer" in list(table["job"])
    finally:
        reset_logging()


def test_background_runs_applies_failed_status_from_navigation_query_parameter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    database_path = data_dir / "database" / "job_application_copilot.db"
    database_path.parent.mkdir(parents=True)
    seed_failed_task(database_path)
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    try:
        app.query_params["status"] = "FAILED"
        app.switch_page("pages/background_runs.py").run()

        assert not app.exception
        assert app.selectbox(key=FILTER_STATUS_KEY).value == "FAILED"
        assert app.query_params.get("status") is None
    finally:
        reset_logging()


def test_background_runs_retries_all_failed_tasks_after_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    database_path = data_dir / "database" / "job_application_copilot.db"
    database_path.parent.mkdir(parents=True)
    first_task_id = seed_failed_task(database_path)
    second_task_id = seed_failed_task(database_path)
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    try:
        app.switch_page("pages/background_runs.py").run()

        assert not app.exception
        assert app.button(key="retry_all_failed_tasks").disabled is True

        app.checkbox(key=RETRY_ALL_CONFIRMATION_KEY).check().run()
        app.button(key="retry_all_failed_tasks").click().run()

        database = create_database(database_path)
        try:
            with database.session() as session:
                tasks = [
                    BackgroundTaskRepository(session).require(first_task_id),
                    BackgroundTaskRepository(session).require(second_task_id),
                ]
                assert all(task.status is BackgroundTaskStatus.PENDING for task in tasks)
                assert all(task.retry_count == 1 for task in tasks)
        finally:
            database.dispose()
    finally:
        reset_logging()
