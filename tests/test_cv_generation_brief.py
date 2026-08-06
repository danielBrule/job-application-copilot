"""Focused validation tests for the reusable first-generation brief."""

import json

import pytest
from pydantic import ValidationError

from job_application_copilot.domain import CvGenerationBriefOutput
from job_application_copilot.services.cv_generation_brief import CvGenerationBriefService
from job_application_copilot.services.cv_generation_context import (
    CvGenerationCacheIdentity,
    CvGenerationContext,
    CvGenerationTextInput,
    CvGenerationTraceability,
)


def payload() -> dict[str, object]:
    return {
        "target_cv_lane": "DATA_LEAD",
        "primary_narrative": "Evidence-led data leadership.",
        "secondary_angle": None,
        "evidence_to_lead_with": ["Validated delivery evidence."],
        "evidence_to_downplay_or_exclude": [],
        "professional_summary_direction": "Lead with operating impact.",
        "experience_emphases": [{"target": "Relevant role", "direction": "Emphasise delivery."}],
        "independent_work_treatment": "Frame as independent work.",
        "skills_section_direction": "Use only evidenced skills.",
        "overclaiming_risks": ["Do not imply sole ownership."],
        "proposed_cv_structure": ["Profile", "Experience"],
        "selected_section_ids": ["summary-1"],
        "selected_passage_ids": [],
        "guardrail_ids": ["guardrails"],
    }


def context() -> CvGenerationContext:
    return CvGenerationContext(
        input=(
            CvGenerationTextInput(
                section="mandatory_document_b",
                text=json.dumps([{"section_id": "summary-1", "logical_id": "guardrails"}]),
            ),
        ),
        stable_prefix_item_count=1,
        cache_boundary_index=0,
        traceability=CvGenerationTraceability(
            stage=1,
            model_identifier="gpt-5.6-sol",
            document_a_version=1,
            document_b_version=1,
            document_b_hash="sha256:x",
            routing_set_id=1,
            routing_config_version="v1",
            routing_config_hash="sha256:y",
            prompt_asset_key="cv-generation-en-stage-1",
            prompt_version=1,
            prompt_hash="sha256:z",
            schema_hash="sha256:s",
        ),
        cache_identity=CvGenerationCacheIdentity(
            identity_version=1,
            identity_hash="a" * 64,
            stage=1,
            model_identifier="gpt-5.6-sol",
            primary_lane="DATA_LEAD",
        ),
        secondary_lane=None,
    )


def test_validates_generic_emphasis_and_authorised_identifiers() -> None:
    output = CvGenerationBriefService._validated_output(json.dumps(payload()), context())

    assert output.experience_emphases[0].target == "Relevant role"
    assert output.selected_section_ids == {"summary-1"}


def test_rejects_an_unauthorised_document_b_selection() -> None:
    values = payload()
    values["selected_section_ids"] = ["not-authorised"]

    with pytest.raises(ValueError, match="unauthorised"):
        CvGenerationBriefService._validated_output(json.dumps(values), context())


def test_requires_the_generic_structured_brief_fields() -> None:
    values = payload()
    del values["experience_emphases"]

    assert CvGenerationBriefOutput.model_validate(values).experience_emphases == ()
    values["evidence_to_lead_with"] = []
    with pytest.raises(ValidationError):
        CvGenerationBriefOutput.model_validate(values)
