"""Validated structured output from English CV-generation stage two."""

from pydantic import BaseModel, ConfigDict, field_validator

from job_application_copilot.domain.final_cv import UNRESOLVED_TEMPLATE_PLACEHOLDER_PATTERN


def _without_unresolved_placeholder(value: str) -> str:
    cleaned = value.strip()
    if match := UNRESOLVED_TEMPLATE_PLACEHOLDER_PATTERN.search(cleaned):
        raise ValueError(f"must not contain unresolved template placeholder {match.group()}")
    return cleaned


class CvGenerationDraftOutput(BaseModel):
    """A reusable tailored-CV draft and its evidence-editing record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_cv: str
    prioritised_evidence: tuple[str, ...] = ()
    softened_evidence: tuple[str, ...] = ()
    excluded_evidence: tuple[str, ...] = ()

    @field_validator("draft_cv", mode="before")
    @classmethod
    def require_draft(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return _without_unresolved_placeholder(value)
        raise ValueError("must be non-blank text")

    @field_validator("prioritised_evidence", "softened_evidence", "excluded_evidence")
    @classmethod
    def require_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_without_unresolved_placeholder(value) for value in values)
        if any(not value for value in cleaned):
            raise ValueError("items must be non-blank text")
        return cleaned
