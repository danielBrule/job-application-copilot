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


def test_rejects_missing_or_blank_structured_draft_fields() -> None:
    values = payload()
    values["draft_cv"] = " "
    with pytest.raises(ValidationError):
        CvGenerationDraftOutput.model_validate(values)

    values = payload()
    values["softened_evidence"] = [""]
    with pytest.raises(ValidationError):
        CvGenerationDraftOutput.model_validate(values)
