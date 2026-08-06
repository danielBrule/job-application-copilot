"""Focused validation tests for final CV-generation stage output."""

import json

import pytest
from pydantic import ValidationError

from job_application_copilot.domain import (
    CvTemplateManifest,
    CvTemplateManifestStatus,
    CvTemplateSlotKind,
    CvTemplateSlotMapping,
)
from job_application_copilot.services.cv_generation_final import CvGenerationFinalService
from job_application_copilot.services.cv_template_contract import (
    CvTemplateContract,
    CvTemplateContractError,
)
from tests.test_final_cv import payload


def test_validates_final_structured_output() -> None:
    output = CvGenerationFinalService._validated_output(json.dumps(payload()))

    assert output.opening_title.content == "AI & Data Solution Architecture Leader"


def test_rejects_invalid_final_structured_output() -> None:
    values = payload()
    values["experience"] = []

    with pytest.raises(ValidationError):
        CvGenerationFinalService._validated_output(json.dumps(values))


def test_contract_rejects_missing_or_invented_experience_placeholder() -> None:
    contract = CvTemplateContract(
        CvTemplateManifest(
            template_asset_id=1,
            status=CvTemplateManifestStatus.CONFIRMED,
            placeholders=("[OPENING_TITLE]", "[OPENING_PROFILE]", "[SKILLS]", "[EXPERIENCE_ONE]"),
            slots=(
                CvTemplateSlotMapping(placeholder="[OPENING_TITLE]", kind=CvTemplateSlotKind.OPENING_TITLE),
                CvTemplateSlotMapping(placeholder="[OPENING_PROFILE]", kind=CvTemplateSlotKind.OPENING_PROFILE),
                CvTemplateSlotMapping(placeholder="[SKILLS]", kind=CvTemplateSlotKind.SKILLS),
                CvTemplateSlotMapping(placeholder="[EXPERIENCE_ONE]", kind=CvTemplateSlotKind.EXPERIENCE, experience_target="One"),
            ),
        )
    )
    output = CvGenerationFinalService._validated_output(json.dumps(payload()))

    with pytest.raises(CvTemplateContractError, match="experience placeholders"):
        contract.validate(output)
