"""Validated mappings between generated CV content and DOCX placeholders."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from job_application_copilot.domain.final_cv import PLACEHOLDER_PATTERN


class CvTemplateManifestStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"


class CvTemplateSlotKind(StrEnum):
    OPENING_TITLE = "OPENING_TITLE"
    OPENING_PROFILE = "OPENING_PROFILE"
    EXPERIENCE = "EXPERIENCE"
    EXPERIENCE_TITLE = "EXPERIENCE_TITLE"
    SKILLS = "SKILLS"


class CvTemplateSlotMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    placeholder: str
    kind: CvTemplateSlotKind
    experience_target: str | None = None

    @field_validator("placeholder", "experience_target", mode="before")
    @classmethod
    def clean_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("must be non-blank text")

    @field_validator("placeholder")
    @classmethod
    def require_placeholder(cls, value: str) -> str:
        if PLACEHOLDER_PATTERN.fullmatch(value) is None:
            raise ValueError("must be a bracketed uppercase DOCX placeholder")
        return value

    @model_validator(mode="after")
    def validate_target(self) -> "CvTemplateSlotMapping":
        if self.kind in {CvTemplateSlotKind.EXPERIENCE, CvTemplateSlotKind.EXPERIENCE_TITLE}:
            if self.experience_target is None:
                raise ValueError("experience slots require an experience target")
        elif self.experience_target is not None:
            raise ValueError("only experience slots may have an experience target")
        return self


class CvTemplateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template_asset_id: int = Field(gt=0)
    status: CvTemplateManifestStatus
    placeholders: tuple[str, ...] = Field(min_length=1)
    slots: tuple[CvTemplateSlotMapping, ...] = ()

    @field_validator("placeholders")
    @classmethod
    def require_unique_placeholders(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("template placeholders must be unique")
        for value in values:
            if PLACEHOLDER_PATTERN.fullmatch(value) is None:
                raise ValueError("template placeholders must use bracketed uppercase syntax")
        return values

    @model_validator(mode="after")
    def validate_slots(self) -> "CvTemplateManifest":
        configured = tuple(slot.placeholder for slot in self.slots)
        if len(configured) != len(set(configured)):
            raise ValueError("template slots must be uniquely mapped")
        if self.status is CvTemplateManifestStatus.CONFIRMED and set(configured) != set(
            self.placeholders
        ):
            raise ValueError("confirmed manifests must map every discovered placeholder")
        return self
