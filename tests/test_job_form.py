"""Tests for shared job-form validation and command mapping."""

from datetime import date

import pytest
from pydantic import ValidationError

from job_application_copilot.domain import Language, Location, UserDecision
from job_application_copilot.repositories.models import Job
from job_application_copilot.ui.components.job_form import (
    JobFormData,
    validation_messages,
)


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
        JobFormData.model_validate(values)

    assert validation_messages(captured.value) == [f"{label} is required."]


def test_valid_form_data_normalizes_short_fields_and_maps_to_command() -> None:
    form_data = JobFormData.model_validate(valid_form_data())

    command = form_data.to_create_command()

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

    command = JobFormData.model_validate(values).to_create_command()

    assert command.job_url is None
    assert command.general_notes is None


def test_update_command_replaces_form_fields_and_preserves_other_job_state() -> None:
    current_job = Job(
        id=7,
        company="Old company",
        job_title="Old title",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_url=None,
        job_description="Old description",
        date_added=date(2026, 7, 1),
        general_notes=None,
        user_decision=UserDecision.PURSUE,
        application_status="Interview",
        application_date=date(2026, 7, 2),
        next_action="Prepare",
        next_action_date=date(2026, 7, 30),
        salary_expectation="GBP 150,000",
        closure_reason=None,
    )

    command = JobFormData.model_validate(valid_form_data()).to_update_command(current_job)

    assert command.company == "Example Ltd"
    assert command.job_title == "Platform Engineer"
    assert command.job_url == "https://example.com/job"
    assert command.user_decision is UserDecision.PURSUE
    assert command.application_status == "Interview"
    assert command.application_date == date(2026, 7, 2)
    assert command.next_action == "Prepare"
    assert command.next_action_date == date(2026, 7, 30)
    assert command.salary_expectation == "GBP 150,000"
    assert command.closure_reason is None
