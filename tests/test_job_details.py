"""Tests for Job Details input handling."""

import pytest

from job_application_copilot.ui.components.job_details import parse_job_id


@pytest.mark.parametrize("value", [None, "", "abc", "1.5", "0", "-1"])
def test_parse_job_id_rejects_missing_or_invalid_values(value: str | None) -> None:
    with pytest.raises(ValueError):
        parse_job_id(value)


def test_parse_job_id_accepts_positive_integer() -> None:
    assert parse_job_id("42") == 42
