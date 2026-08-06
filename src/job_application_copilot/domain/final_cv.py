"""Template-parameterised structured content for a final generated CV."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PLACEHOLDER_PATTERN = re.compile(r"^\[[A-Z][A-Z0-9_]*\]$")


class CvTemplateText(BaseModel):
    """One generated text value assigned to a configurable DOCX placeholder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    placeholder: str
    content: str

    @field_validator("placeholder", "content", mode="before")
    @classmethod
    def require_text(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("must be non-blank text")

    @field_validator("placeholder")
    @classmethod
    def require_placeholder(cls, value: str) -> str:
        if PLACEHOLDER_PATTERN.fullmatch(value) is None:
            raise ValueError("must be a bracketed uppercase DOCX placeholder")
        return value


class CvExperienceBlock(BaseModel):
    """Generated content for one configurable professional-experience placeholder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    placeholder: str
    title: CvTemplateText | None = None
    introduction: str | None = None
    bullets: tuple[str, ...] = Field(min_length=1)

    @field_validator("placeholder", "introduction", mode="before")
    @classmethod
    def require_optional_text(cls, value: object) -> object:
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

    @field_validator("bullets")
    @classmethod
    def require_bullets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("bullets must be non-blank text")
        return cleaned


class CvSkillEntry(BaseModel):
    """One skill rendered as ``name: content`` by the DOCX renderer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    content: str

    @field_validator("name", "content", mode="before")
    @classmethod
    def require_text(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("must be non-blank text")


class CvSkillsBlock(BaseModel):
    """Ordered skill entries assigned to one configurable DOCX placeholder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    placeholder: str
    entries: tuple[CvSkillEntry, ...] = Field(min_length=1)

    @field_validator("placeholder", mode="before")
    @classmethod
    def require_placeholder_text(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError("must be non-blank text")

    @field_validator("placeholder")
    @classmethod
    def require_placeholder(cls, value: str) -> str:
        if PLACEHOLDER_PATTERN.fullmatch(value) is None:
            raise ValueError("must be a bracketed uppercase DOCX placeholder")
        return value


class FinalCvOutput(BaseModel):
    """Validated generated content for a configurable final-CV DOCX template."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_title: CvTemplateText
    opening_profile: CvTemplateText
    experience: tuple[CvExperienceBlock, ...] = Field(min_length=1)
    skills: CvSkillsBlock

    @model_validator(mode="after")
    def require_unique_placeholders(self) -> "FinalCvOutput":
        placeholders = [self.opening_title.placeholder, self.opening_profile.placeholder]
        placeholders.append(self.skills.placeholder)
        for experience in self.experience:
            placeholders.append(experience.placeholder)
            if experience.title is not None:
                placeholders.append(experience.title.placeholder)
        if len(placeholders) != len(set(placeholders)):
            raise ValueError("each generated value must have a unique DOCX placeholder")
        return self
