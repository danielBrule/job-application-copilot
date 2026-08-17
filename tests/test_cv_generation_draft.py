"""Focused validation tests for the reusable second-generation CV draft."""

import json

import pytest
from pydantic import ValidationError

from job_application_copilot.domain import CvGenerationDraftOutput
from job_application_copilot.services.cv_generation_draft import CvGenerationDraftService


def payload() -> dict[str, object]:
    return {
        "draft_cv": "Candidate Name\n\nProfessional Profile\nEvidence-led data leader.",
        "prioritised_evidence": ["Validated delivery evidence."],
        "softened_evidence": ["Independent work is framed cautiously."],
        "excluded_evidence": ["Unsupported ownership claim."],
    }


def test_validates_the_structured_draft_and_evidence_notes() -> None:
    output = CvGenerationDraftService._validated_output(json.dumps(payload()))

    assert output.prioritised_evidence == ("Validated delivery evidence.",)
    assert "Professional Profile" in output.draft_cv


def test_accepts_placeholder_words_in_ordinary_stage_two_prose() -> None:
    values = payload()
    values["draft_cv"] = "Led company delivery across locations and reporting dates."

    output = CvGenerationDraftOutput.model_validate(values)

    assert output.draft_cv.startswith("Led company delivery")


def test_rejects_missing_or_blank_structured_draft_fields() -> None:
    values = payload()
    values["draft_cv"] = " "
    with pytest.raises(ValidationError):
        CvGenerationDraftOutput.model_validate(values)

    values = payload()
    values["softened_evidence"] = [""]
    with pytest.raises(ValidationError):
        CvGenerationDraftOutput.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("draft_cv", "Experience at [Company]."),
        ("prioritised_evidence", ["Use [Actual job title] as supplied."]),
        ("softened_evidence", ["Scope at [Location] is not evidenced."]),
        ("excluded_evidence", ["Dates remain [Dates]."]),
    ],
)
def test_rejects_unresolved_placeholders_in_every_stage_two_field(
    field: str, value: object
) -> None:
    values = payload()
    values[field] = value

    with pytest.raises(ValidationError, match="unresolved template placeholder"):
        CvGenerationDraftOutput.model_validate(values)
