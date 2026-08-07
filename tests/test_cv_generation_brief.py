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
        "mandate_coverage": [
            {
                "mandate_dimension_id": "delivery",
                "planned_evidence": "Validated delivery evidence.",
                "coverage_status": "COVERED",
            }
        ],
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
                text=json.dumps(
                    [
                        {
                            "section_id": "summary-1",
                            "logical_id": "guardrails",
                            "role": "GUARDRAIL",
                        }
                    ]
                ),
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
    values = payload()
    del values["target_cv_lane"]

    output = CvGenerationBriefService._validated_output(json.dumps(values), context())

    assert output.experience_emphases[0].target == "Relevant role"
    assert output.selected_section_ids == {"summary-1"}
    assert output.target_cv_lane == "DATA_LEAD"


def test_stage_one_schema_excludes_application_controlled_values() -> None:
    schema = CvGenerationBriefService._model_response_schema()

    assert "target_cv_lane" not in schema["properties"]
    assert "target_cv_lane" not in schema["required"]
    assert "selected_passage_ids" not in schema["properties"]
    assert "selected_passage_ids" not in schema["required"]
    assert "guardrail_ids" not in schema["properties"]
    assert "guardrail_ids" not in schema["required"]


def test_overrides_a_model_returned_lane_with_the_confirmed_lane() -> None:
    values = payload()
    values["target_cv_lane"] = "UNRELATED_LANE"
    values["selected_passage_ids"] = ["not-supplied"]

    output = CvGenerationBriefService._validated_output(json.dumps(values), context())

    assert output.target_cv_lane == "DATA_LEAD"
    assert output.selected_passage_ids == frozenset()


def test_supplies_all_authorised_guardrails_without_trusting_model_selection() -> None:
    values = payload()
    values["guardrail_ids"] = ["made-up-guardrail"]

    output = CvGenerationBriefService._validated_output(json.dumps(values), context())

    assert output.guardrail_ids == {"guardrails"}


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
