"""Focused validation tests for final CV-generation stage output."""

import json

import pytest
from pydantic import ValidationError

from job_application_copilot.services.cv_generation_final import CvGenerationFinalService
from tests.test_final_cv import payload


def test_validates_final_structured_output() -> None:
    output = CvGenerationFinalService._validated_output(json.dumps(payload()))

    assert output.opening_title.content == "AI & Data Solution Architecture Leader"


def test_rejects_invalid_final_structured_output() -> None:
    values = payload()
    values["experience"] = []

    with pytest.raises(ValidationError):
        CvGenerationFinalService._validated_output(json.dumps(values))
