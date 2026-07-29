"""Validation tests for the exact model-produced assessment contract."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentOutput,
    Relevance,
    assessment_output_json_schema,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "assessment_output_valid.json"
ALLOWED_LANES = {
    "FICTIONAL_ARCHITECTURE_LEAD",
    "FICTIONAL_AI_DEPLOYMENT_LEAD",
}


def valid_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def validate(payload: dict[str, object]) -> AssessmentOutput:
    return AssessmentOutput.model_validate(
        payload,
        context={"allowed_lane_ids": ALLOWED_LANES},
    )


def test_parses_sanitized_saved_assessment_example() -> None:
    parsed = AssessmentOutput.model_validate_json(
        FIXTURE_PATH.read_text(encoding="utf-8"),
        context={"allowed_lane_ids": ALLOWED_LANES},
    )

    assert parsed.model_relevance is Relevance.HIGH
    assert parsed.decision is AssessmentDecision.GO
    assert parsed.primary_role_family == "FICTIONAL_ARCHITECTURE_LEAD"
    assert parsed.secondary_cv_angle is None
    assert parsed.evidence_anchors[0].source_reference == "A-FICTIONAL-01"


@pytest.mark.parametrize(
    "field",
    [
        "seniority_fit",
        "tech_bar_fit",
        "fit_score",
        "priority_score",
        "interview_probability_low",
        "interview_probability_high",
        "interview_probability_confidence",
        "evidence_confidence",
    ],
)
@pytest.mark.parametrize("value", [-1, 11, 7.5, "7"])
def test_rejects_invalid_or_non_integer_scores(field: str, value: object) -> None:
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(ValidationError) as captured:
        validate(payload)

    assert field in str(captured.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_relevance", "URGENT"),
        ("decision", "MAYBE"),
        ("primary_role_family", "NOT_CONFIGURED"),
        ("secondary_role_family", "NOT_CONFIGURED"),
        ("recommended_document_b_lane", "NOT_CONFIGURED"),
    ],
)
def test_rejects_invalid_enums_and_unconfigured_lanes(field: str, value: object) -> None:
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(ValidationError) as captured:
        validate(payload)

    assert field in str(captured.value)


def test_rejects_missing_relevance() -> None:
    payload = valid_payload()
    del payload["model_relevance"]

    with pytest.raises(ValidationError, match="model_relevance"):
        validate(payload)


def test_rejects_reversed_interview_range() -> None:
    payload = valid_payload()
    payload["interview_probability_low"] = 8
    payload["interview_probability_high"] = 3

    with pytest.raises(ValidationError, match="less than or equal"):
        validate(payload)


@pytest.mark.parametrize("field", ["role_snapshot", "real_mandate", "technical_bar"])
def test_rejects_blank_required_text(field: str) -> None:
    payload = valid_payload()
    payload[field] = " "

    with pytest.raises(ValidationError, match=field):
        validate(payload)


def test_requires_secondary_angle_but_accepts_null() -> None:
    payload = valid_payload()
    del payload["secondary_cv_angle"]

    with pytest.raises(ValidationError, match="secondary_cv_angle"):
        validate(payload)

    payload["secondary_cv_angle"] = None
    assert validate(payload).secondary_cv_angle is None


def test_rejects_malformed_evidence_anchor() -> None:
    payload = valid_payload()
    payload["evidence_anchors"] = [{"source_reference": "A-1", "evidence": "Fact"}]

    with pytest.raises(ValidationError, match="supports"):
        validate(payload)


def test_rejects_extra_model_owned_or_user_owned_fields() -> None:
    payload = valid_payload()
    payload["relevance_override"] = "LOW"

    with pytest.raises(ValidationError, match="relevance_override"):
        validate(payload)


def test_requires_allowed_lane_validation_context() -> None:
    with pytest.raises(ValidationError, match="allowed_lane_ids"):
        AssessmentOutput.model_validate(valid_payload())


def test_allows_explicitly_empty_collections_but_not_blank_items() -> None:
    payload = valid_payload()
    payload["red_flags"] = []
    payload["sustainability_risks"] = [" "]

    with pytest.raises(ValidationError, match="items must not be blank"):
        validate(payload)

    payload["sustainability_risks"] = []
    assert validate(payload).sustainability_risks == ()


def test_provider_schema_uses_configured_lanes_as_exact_enums() -> None:
    schema = assessment_output_json_schema(ALLOWED_LANES)

    for field in (
        "primary_role_family",
        "secondary_role_family",
        "recommended_document_b_lane",
    ):
        assert schema["properties"][field]["enum"] == sorted(ALLOWED_LANES)


def test_provider_schema_rejects_empty_or_invalid_lane_catalogue() -> None:
    with pytest.raises(ValueError, match="at least one"):
        assessment_output_json_schema(set())
    with pytest.raises(ValidationError):
        assessment_output_json_schema({"not valid"})
