"""Shared pytest fixtures."""

import pytest

from job_application_copilot.ui.dependencies import get_database


@pytest.fixture(autouse=True)
def clear_ui_database_cache() -> None:
    """Isolate Streamlit's cached database resource between tests."""

    get_database.clear()
    yield
    get_database.clear()
