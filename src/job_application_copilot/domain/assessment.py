"""Stable assessment domain values."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

from job_application_copilot.domain.document_b_routing import LaneId
from job_application_copilot.domain.job import Relevance

ASSESSMENT_SCHEMA_VERSION = 1


class AssessmentStatus(StrEnum):
    """Lifecycle of the single current assessment for a job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    ASSESSED = "ASSESSED"
    FAILED = "FAILED"


class AssessmentDecision(StrEnum):
    """GO: strong direct evidence with manageable gaps. CAUTION: credible fit needing clarification of attractiveness, sustainability, authority, scope, or operating model. STRETCH: relevant role and credible, non-overclaiming application, but material gaps make an interview uncertain. NO_GO: structural mandate mismatch, several missing non-negotiables, or material overclaiming required. Prefer STRETCH for one or two weak requirements; prefer CAUTION or STRETCH when team support or responsibilities are unknown."""

    GO = "GO"
    CAUTION = "CAUTION"
    STRETCH = "STRETCH"
    NO_GO = "NO_GO"


Score = Annotated[StrictInt, Field(ge=0, le=10)]
LANE_ID_ADAPTER = TypeAdapter(LaneId)


class AssessmentEvidenceAnchor(BaseModel):
    """One traceable Document A fact and the assessment inference it supports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_reference: str
    evidence: str
    supports: str

    @field_validator("source_reference", "evidence", "supports", mode="before")
    @classmethod
    def require_non_blank_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("must not be blank")
        return value


class MandateEvidenceStrength(StrEnum):
    """How directly Document A supports one material JD mandate dimension."""

    DIRECT = "DIRECT"
    ADJACENT = "ADJACENT"
    WEAK = "WEAK"
    NONE = "NONE"


class AssessmentMandateDimension(BaseModel):
    """A compact, evidence-grounded requirement retained for CV coverage planning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    description: str
    importance: Score
    evidence_strength: MandateEvidenceStrength
    evidence_anchor_refs: tuple[str, ...] = ()
    should_shape_cv: bool

    @field_validator("id", "description", mode="before")
    @classmethod
    def require_non_blank_text(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("must be non-blank text")

    @field_validator("evidence_anchor_refs")
    @classmethod
    def require_non_blank_anchor_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("items must be non-blank text")
        return cleaned

    @model_validator(mode="after")
    def require_anchor_for_supported_dimension(self) -> "AssessmentMandateDimension":
        if (
            self.evidence_strength is not MandateEvidenceStrength.NONE
            and not self.evidence_anchor_refs
        ):
            raise ValueError("supported mandate dimensions require evidence_anchor_refs")
        return self


class AssessmentOutput(BaseModel):
    """Exact model-produced assessment response validated before persistence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_relevance: Relevance
    role_snapshot: str
    real_mandate: str
    primary_role_family: LaneId
    secondary_role_family: LaneId | None
    seniority_fit: Score
    technical_bar: str
    tech_bar_fit: Score
    fit_score: Score
    priority_score: Score
    decision: AssessmentDecision
    decision_reason: str
    interview_probability_low: Score
    interview_probability_high: Score
    interview_probability_confidence: Score
    strong_fit_signals: tuple[str, ...]
    red_flags: tuple[str, ...]
    sustainability_risks: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    evidence_anchors: tuple[AssessmentEvidenceAnchor, ...]
    material_mandate_dimensions: tuple[AssessmentMandateDimension, ...] = Field(
        min_length=1, max_length=7
    )
    evidence_confidence: Score
    recommended_document_b_lane: LaneId
    secondary_cv_angle: LaneId | None
    overclaiming_risks: tuple[str, ...]

    @field_validator(
        "role_snapshot",
        "real_mandate",
        "technical_bar",
        "decision_reason",
        "secondary_cv_angle",
        mode="before",
    )
    @classmethod
    def require_non_blank_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("must not be blank")
        return value

    @field_validator(
        "strong_fit_signals",
        "red_flags",
        "sustainability_risks",
        "evidence_gaps",
        "overclaiming_risks",
    )
    @classmethod
    def require_non_blank_collection_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("items must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_ranges_and_configured_lanes(self, info: ValidationInfo) -> "AssessmentOutput":
        if self.interview_probability_low > self.interview_probability_high:
            raise ValueError(
                "interview_probability_low must be less than or equal to interview_probability_high"
            )

        context: dict[str, Any] = info.context or {}
        raw_allowed_lanes = context.get("allowed_lane_ids")
        if raw_allowed_lanes is None:
            raise ValueError("assessment validation requires configured allowed_lane_ids")
        allowed_lanes = frozenset(raw_allowed_lanes)
        if not allowed_lanes:
            raise ValueError("assessment validation requires at least one allowed lane")

        for field_name in (
            "primary_role_family",
            "secondary_role_family",
            "recommended_document_b_lane",
            "secondary_cv_angle",
        ):
            lane = getattr(self, field_name)
            if lane is None:
                continue
            if lane not in allowed_lanes:
                raise ValueError(f"{field_name} '{lane}' is not configured")
        return self


def assessment_output_json_schema(allowed_lane_ids: Iterable[object]) -> dict[str, Any]:
    """Build the provider schema with lanes from the active validated routing set."""

    lanes = sorted({LANE_ID_ADAPTER.validate_python(lane) for lane in allowed_lane_ids})
    if not lanes:
        raise ValueError("allowed_lane_ids must contain at least one configured lane")

    schema = AssessmentOutput.model_json_schema()
    properties = schema["properties"]
    for field_name in ("primary_role_family", "recommended_document_b_lane"):
        properties[field_name]["enum"] = lanes
    for field_name in ("secondary_role_family", "secondary_cv_angle"):
        secondary_options = properties[field_name]["anyOf"]
        secondary_lane_schema = next(
            option for option in secondary_options if option.get("type") == "string"
        )
        secondary_lane_schema["enum"] = lanes
    return schema
