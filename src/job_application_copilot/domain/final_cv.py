"""Template-parameterised structured content for a final generated CV."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PLACEHOLDER_PATTERN = re.compile(r"^\[[A-Z][A-Z0-9_]*\]$")
UNRESOLVED_TEMPLATE_PLACEHOLDER_PATTERN = re.compile(
    r"\[(?:factual|actual)?\s*(?:job\s*)?title|company|location|dates?\]",
    re.IGNORECASE,
)
SERIALIZATION_DELIMITER_PATTERN = re.compile(r"\]\s*}\s*,\s*{")
DELIMITER_ONLY_PATTERN = re.compile(r'^[\s\[\]{} ,:"]+$')


def _require_cv_prose(value: object) -> str:
    """Reject blank text and JSON-like serialization fragments in generated CV prose."""

    if not isinstance(value, str) or not (cleaned := value.strip()):
        raise ValueError("must be non-blank text")
    if (match := UNRESOLVED_TEMPLATE_PLACEHOLDER_PATTERN.search(cleaned)) is not None:
        raise ValueError(f"must not contain unresolved template placeholder {match.group()}")
    if (
        DELIMITER_ONLY_PATTERN.fullmatch(cleaned) is not None
        or SERIALIZATION_DELIMITER_PATTERN.search(cleaned) is not None
    ):
        raise ValueError("must not contain a structured-output serialization fragment")
    return cleaned


class CvTemplateText(BaseModel):
    """One generated text value assigned to a configurable DOCX placeholder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    placeholder: str
    content: str

    @field_validator("placeholder", "content", mode="before")
    @classmethod
    def require_text(cls, value: object) -> object:
        return _require_cv_prose(value)

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
        return _require_cv_prose(value)

    @field_validator("placeholder")
    @classmethod
    def require_placeholder(cls, value: str) -> str:
        if PLACEHOLDER_PATTERN.fullmatch(value) is None:
            raise ValueError("must be a bracketed uppercase DOCX placeholder")
        return value

    @field_validator("bullets")
    @classmethod
    def require_bullets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_require_cv_prose(value) for value in values)


class CvSkillEntry(BaseModel):
    """One skill rendered as ``name: content`` by the DOCX renderer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    content: str

    @field_validator("name", "content", mode="before")
    @classmethod
    def require_text(cls, value: object) -> object:
        return _require_cv_prose(value)


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


class SemanticCvExperienceBlock(BaseModel):
    """Stage-three experience content before local template-slot assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str | None = None
    introduction: str | None = None
    bullets: tuple[str, ...] = Field(min_length=1)

    @field_validator("title", "introduction", mode="before")
    @classmethod
    def require_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        return _require_cv_prose(value)

    @field_validator("bullets")
    @classmethod
    def require_bullets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_require_cv_prose(value) for value in values)


class SemanticFinalCvOutput(BaseModel):
    """Stage-three content whose DOCX slots are assigned locally and deterministically."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_title: str
    opening_profile: str
    experience: tuple[SemanticCvExperienceBlock, ...] = Field(min_length=1)
    skills: tuple[CvSkillEntry, ...] = Field(min_length=1)

    @field_validator("opening_title", "opening_profile", mode="before")
    @classmethod
    def require_text(cls, value: object) -> object:
        return _require_cv_prose(value)


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
