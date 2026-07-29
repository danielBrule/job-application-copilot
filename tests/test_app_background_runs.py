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
    FILTER_BATCH_KEY,
    FILTER_JOB_KEY,
    FILTER_OPERATION_KEY,
    FILTER_STATUS_KEY,
    REFRESH_BUTTON_KEY,
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


def test_background_runs_filters_history_and_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    database_path = data_dir / "database" / "job_application_copilot.db"
    database_path.parent.mkdir(parents=True)
    task_id = seed_failed_task(database_path)
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
        assert any("Attempt history (1)" in expander.label for expander in app.expander)
        assert any(error.value == "Visible local task error." for error in app.error)

        app.button(key=f"background_run_retry_{task_id}").click().run()

        assert not app.exception
        database = create_database(database_path)
        try:
            with database.session() as session:
                task = BackgroundTaskRepository(session).require(task_id)
                assert task.status is BackgroundTaskStatus.PENDING
                assert task.retry_count == 1
        finally:
            database.dispose()
    finally:
        reset_logging()
