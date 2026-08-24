"""Tests for operational dashboard presentation."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from job_application_copilot.observability import reset_logging
from job_application_copilot.ui.components.dashboard import (
    _duration_total_and_average,
    _total_and_average,
)
from tests.app_test_support import APP_PATH


def test_usage_kpi_values_show_totals_and_successful_call_averages() -> None:
    assert _total_and_average(1_250, 625.0) == "625.0 avg / 1,250 total"
    assert _total_and_average(0, None) == "— avg / 0 total"
    assert _duration_total_and_average(2.25, 1.5) == "1.50 s avg / 2.25 s total"
    assert _duration_total_and_average(0.0, None) == "— avg / 0.00 s total"


def test_dashboard_shows_usage_and_failed_task_kpis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        app.switch_page("pages/dashboard.py").run()

        assert not app.exception
        assert app.title[0].value == "Dashboard"
        assert any(
            metric.label == "Assessment tokens" and metric.value == "— avg / 0 total"
            for metric in app.metric
        )
        assert any(
            metric.label == "Failed tasks requiring attention" and metric.value == "0"
            for metric in app.metric
        )
        assert {metric.label for metric in app.metric}.issuperset(
            {
                "Jobs",
                "Assessed jobs",
                "Applied jobs",
                "Unassessed jobs",
                "Selected without generated CV",
            }
        )
        assert any(page_link.label == "Review failed tasks" for page_link in app.get("page_link"))
    finally:
        reset_logging()
