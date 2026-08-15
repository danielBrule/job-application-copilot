"""Focused validation tests for final CV-generation stage output."""

import json

import pytest
from pydantic import ValidationError

from job_application_copilot.domain import (
    CvTemplateManifest,
    CvTemplateManifestStatus,
    CvTemplateSlotKind,
    CvTemplateSlotMapping,
    CvTemplateText,
)
from job_application_copilot.services.cv_generation_final import CvGenerationFinalService
from job_application_copilot.services.cv_template_contract import (
    CvTemplateContract,
    CvTemplateContractError,
)
from tests.test_final_cv import payload


def semantic_payload() -> dict[str, object]:
    values = payload()
    return {
        "opening_title": values["opening_title"]["content"],
        "opening_profile": values["opening_profile"]["content"],
        "experience": [
            {
                "title": None if item.get("title") is None else item["title"]["content"],
                "introduction": item.get("introduction"),
                "bullets": item["bullets"],
            }
            for item in values["experience"]
        ],
        "skills": values["skills"]["entries"],
    }


def test_validates_final_structured_output() -> None:
    output = CvGenerationFinalService._validated_output(json.dumps(payload()))

    assert output.opening_title.content == "AI & Data Solution Architecture Leader"


def test_rejects_invalid_final_structured_output() -> None:
    values = payload()
    values["experience"] = []

    with pytest.raises(ValidationError):
        CvGenerationFinalService._validated_output(json.dumps(values))


def test_rejects_malformed_experience_serialization_before_final_output_is_stored() -> None:
    values = payload()
    values["experience"][0]["bullets"] = ["]},{"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="serialization fragment"):
        CvGenerationFinalService._validated_output(json.dumps(values))


def test_contract_rejects_missing_or_invented_experience_placeholder() -> None:
    contract = CvTemplateContract(
        CvTemplateManifest(
            template_asset_id=1,
            status=CvTemplateManifestStatus.CONFIRMED,
            placeholders=("[OPENING_TITLE]", "[OPENING_PROFILE]", "[SKILLS]", "[EXPERIENCE_ONE]"),
            slots=(
                CvTemplateSlotMapping(
                    placeholder="[OPENING_TITLE]", kind=CvTemplateSlotKind.OPENING_TITLE
                ),
                CvTemplateSlotMapping(
                    placeholder="[OPENING_PROFILE]", kind=CvTemplateSlotKind.OPENING_PROFILE
                ),
                CvTemplateSlotMapping(placeholder="[SKILLS]", kind=CvTemplateSlotKind.SKILLS),
                CvTemplateSlotMapping(
                    placeholder="[EXPERIENCE_ONE]",
                    kind=CvTemplateSlotKind.EXPERIENCE,
                    experience_target="One",
                ),
            ),
        )
    )
    output = CvGenerationFinalService._validated_output(json.dumps(payload()))

    with pytest.raises(CvTemplateContractError, match="experience placeholders"):
        contract.validate(output)


def test_contract_validation_is_available_to_the_stage_output_validator() -> None:
    contract = CvTemplateContract(
        CvTemplateManifest(
            template_asset_id=1,
            status=CvTemplateManifestStatus.CONFIRMED,
            placeholders=("[OPENING_TITLE]", "[OPENING_PROFILE]", "[SKILLS]", "[EXPERIENCE_ONE]"),
            slots=(
                CvTemplateSlotMapping(
                    placeholder="[OPENING_TITLE]", kind=CvTemplateSlotKind.OPENING_TITLE
                ),
                CvTemplateSlotMapping(
                    placeholder="[OPENING_PROFILE]", kind=CvTemplateSlotKind.OPENING_PROFILE
                ),
                CvTemplateSlotMapping(placeholder="[SKILLS]", kind=CvTemplateSlotKind.SKILLS),
                CvTemplateSlotMapping(
                    placeholder="[EXPERIENCE_ONE]",
                    kind=CvTemplateSlotKind.EXPERIENCE,
                    experience_target="One",
                ),
            ),
        )
    )

    with pytest.raises(CvTemplateContractError, match="experience blocks"):
        CvGenerationFinalService._validated_contract_output(json.dumps(semantic_payload()), contract)


def test_contract_rejects_a_missing_factual_experience_title_when_template_requires_one() -> None:
    values = semantic_payload()
    values["experience"][1]["title"] = None  # type: ignore[index]
    contract = CvTemplateContract(
        CvTemplateManifest(
            template_asset_id=1,
            status=CvTemplateManifestStatus.CONFIRMED,
            placeholders=(
                "[OPENING_TITLE]",
                "[OPENING_PROFILE]",
                "[SKILLS]",
                "[EXPERIENCE_INDEPENDENT_GENAI]",
                "[EXPERIENCE_EKIMETRICS]",
                "[EKIMETRICS_TITLE]",
            ),
            slots=(
                CvTemplateSlotMapping(
                    placeholder="[OPENING_TITLE]", kind=CvTemplateSlotKind.OPENING_TITLE
                ),
                CvTemplateSlotMapping(
                    placeholder="[OPENING_PROFILE]", kind=CvTemplateSlotKind.OPENING_PROFILE
                ),
                CvTemplateSlotMapping(placeholder="[SKILLS]", kind=CvTemplateSlotKind.SKILLS),
                CvTemplateSlotMapping(
                    placeholder="[EXPERIENCE_INDEPENDENT_GENAI]",
                    kind=CvTemplateSlotKind.EXPERIENCE,
                    experience_target="Independent GenAI",
                ),
                CvTemplateSlotMapping(
                    placeholder="[EXPERIENCE_EKIMETRICS]",
                    kind=CvTemplateSlotKind.EXPERIENCE,
                    experience_target="Ekimetrics",
                ),
                CvTemplateSlotMapping(
                    placeholder="[EKIMETRICS_TITLE]",
                    kind=CvTemplateSlotKind.EXPERIENCE_TITLE,
                    experience_target="Ekimetrics",
                ),
            ),
        )
    )

    with pytest.raises(CvTemplateContractError, match="requires a resolved factual title"):
        CvGenerationFinalService._validated_contract_output(json.dumps(values), contract)


def test_contract_normalises_an_experience_title_to_its_matching_slot() -> None:
    output = CvGenerationFinalService._validated_output(json.dumps(payload()))
    first_placeholder = output.experience[0].placeholder
    second_placeholder = output.experience[1].placeholder
    contract = CvTemplateContract(
        CvTemplateManifest(
            template_asset_id=1,
            status=CvTemplateManifestStatus.CONFIRMED,
            placeholders=(
                "[OPENING_TITLE]",
                "[OPENING_PROFILE]",
                "[SKILLS]",
                first_placeholder,
                "[EXPERIENCE_ONE_TITLE]",
                second_placeholder,
                "[EXPERIENCE_TWO_TITLE]",
            ),
            slots=(
                CvTemplateSlotMapping(
                    placeholder="[OPENING_TITLE]", kind=CvTemplateSlotKind.OPENING_TITLE
                ),
                CvTemplateSlotMapping(
                    placeholder="[OPENING_PROFILE]", kind=CvTemplateSlotKind.OPENING_PROFILE
                ),
                CvTemplateSlotMapping(placeholder="[SKILLS]", kind=CvTemplateSlotKind.SKILLS),
                CvTemplateSlotMapping(
                    placeholder=first_placeholder,
                    kind=CvTemplateSlotKind.EXPERIENCE,
                    experience_target="One",
                ),
                CvTemplateSlotMapping(
                    placeholder="[EXPERIENCE_ONE_TITLE]",
                    kind=CvTemplateSlotKind.EXPERIENCE_TITLE,
                    experience_target="One",
                ),
                CvTemplateSlotMapping(
                    placeholder=second_placeholder,
                    kind=CvTemplateSlotKind.EXPERIENCE,
                    experience_target="Two",
                ),
                CvTemplateSlotMapping(
                    placeholder="[EXPERIENCE_TWO_TITLE]",
                    kind=CvTemplateSlotKind.EXPERIENCE_TITLE,
                    experience_target="Two",
                ),
            ),
        )
    )
    first = output.experience[0].model_copy(
        update={"title": CvTemplateText(placeholder="[EXPERIENCE_TWO_TITLE]", content="Role title")}
    )
    output = output.model_copy(update={"experience": (first,) + output.experience[1:]})

    normalised = contract.normalise_experience_titles(output)

    assert normalised.experience[0].title is not None
    assert normalised.experience[0].title.placeholder == "[EXPERIENCE_ONE_TITLE]"
