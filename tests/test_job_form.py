"""Tests for add-job form validation and command mapping."""

from datetime import date

import pytest
from pydantic import ValidationError

from job_application_copilot.domain import Language, Location
from job_application_copilot.ui.job_form import AddJobFormData, validation_messages


def valid_form_data() -> dict[str, object]:
    return {
        "company": " Example Ltd ",
        "job_title": " Platform Engineer ",
        "location": Location.UK,
        "language": Language.EN,
        "source": " LinkedIn ",
        "job_url": " https://example.com/job ",
        "job_description": "  Build and operate reliable systems.\n",
        "date_added": date(2026, 7, 24),
        "general_notes": "Keep the original formatting.\n",
    }


@pytest.mark.parametrize(
    ("field_name", "label"),
    [
        ("company", "Company"),
        ("job_title", "Job title"),
        ("source", "Source"),
        ("job_description", "Full job description"),
    ],
)
def test_required_text_fields_reject_whitespace(
    field_name: str,
    label: str,
) -> None:
    values = valid_form_data()
    values[field_name] = "   "

    with pytest.raises(ValidationError) as captured:
        AddJobFormData.model_validate(values)

    assert validation_messages(captured.value) == [f"{label} is required."]


def test_valid_form_data_normalizes_short_fields_and_maps_to_command() -> None:
    form_data = AddJobFormData.model_validate(valid_form_data())

    command = form_data.to_command()

    assert command.company == "Example Ltd"
    assert command.job_title == "Platform Engineer"
    assert command.location is Location.UK
    assert command.language is Language.EN
    assert command.source == "LinkedIn"
    assert command.job_url == "https://example.com/job"
    assert command.job_description == "  Build and operate reliable systems.\n"
    assert command.date_added == date(2026, 7, 24)
    assert command.general_notes == "Keep the original formatting.\n"


def test_blank_optional_values_become_none() -> None:
    values = valid_form_data()
    values["job_url"] = " "
    values["general_notes"] = "\n"

    command = AddJobFormData.model_validate(values).to_command()

    assert command.job_url is None
    assert command.general_notes is None
