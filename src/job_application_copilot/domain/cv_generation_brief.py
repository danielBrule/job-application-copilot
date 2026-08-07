"""Validated stage-one CV-generation brief values."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CvExperienceEmphasis(BaseModel):
    """How one relevant employer, role, or body of work should be positioned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: str
    direction: str

    @field_validator("target", "direction", mode="before")
    @classmethod
    def require_text(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("must be non-blank text")


class CvMandateCoverageStatus(StrEnum):
    COVERED = "COVERED"
    AUTHORISED_MATERIAL_GAP = "AUTHORISED_MATERIAL_GAP"
    UNSUPPORTED = "UNSUPPORTED"


class CvMandateCoverage(BaseModel):
    """Evidence plan for one material JD requirement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mandate_dimension_id: str
    planned_evidence: str
    coverage_status: CvMandateCoverageStatus

    @field_validator("mandate_dimension_id", "planned_evidence", mode="before")
    @classmethod
    def require_text(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("must be non-blank text")


class CvGenerationBriefOutput(BaseModel):
    """Strict, reusable stage-one selection and writing brief."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_cv_lane: str
    primary_narrative: str
    secondary_angle: str | None = None
    evidence_to_lead_with: tuple[str, ...] = Field(min_length=1)
    evidence_to_downplay_or_exclude: tuple[str, ...] = ()
    mandate_coverage: tuple[CvMandateCoverage, ...] = Field(min_length=1)
    professional_summary_direction: str
    experience_emphases: tuple[CvExperienceEmphasis, ...] = ()
    independent_work_treatment: str
    skills_section_direction: str
    overclaiming_risks: tuple[str, ...]
    proposed_cv_structure: tuple[str, ...] = Field(min_length=1)
    selected_section_ids: frozenset[str]
    selected_passage_ids: frozenset[str] = frozenset()
    guardrail_ids: frozenset[str]

    @field_validator(
        "target_cv_lane",
        "primary_narrative",
        "secondary_angle",
        "professional_summary_direction",
        "independent_work_treatment",
        "skills_section_direction",
        mode="before",
    )
    @classmethod
    def require_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("must be non-blank text")

    @field_validator(
        "evidence_to_lead_with",
        "evidence_to_downplay_or_exclude",
        "overclaiming_risks",
        "proposed_cv_structure",
    )
    @classmethod
    def require_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("items must be non-blank text")
        return cleaned

    @field_validator("selected_section_ids", "selected_passage_ids", "guardrail_ids")
    @classmethod
    def require_identifiers(cls, values: frozenset[str]) -> frozenset[str]:
        cleaned = frozenset(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("identifiers must be non-blank")
        return cleaned
