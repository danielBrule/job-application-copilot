"""Validated prompt-definition commands and completeness results."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROMPT_ASSET_KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
PIPELINE_GROUP_PATTERN = r"^[a-z0-9]+(?:[/-][a-z0-9]+)*$"
LANGUAGE_CODE_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class CreatePromptDefinition(BaseModel):
    """Values required to add one data-driven prompt definition."""

    model_config = ConfigDict(frozen=True)

    asset_key: str = Field(min_length=1, max_length=255, pattern=PROMPT_ASSET_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    pipeline_group: str = Field(
        min_length=1,
        max_length=255,
        pattern=PIPELINE_GROUP_PATTERN,
    )
    language_code: str | None = Field(
        default=None,
        max_length=16,
        pattern=LANGUAGE_CODE_PATTERN,
    )
    position: int = Field(ge=1)
    is_enabled: bool = True

    @field_validator("asset_key", "name", "pipeline_group", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("language_code", mode="before")
    @classmethod
    def normalize_language_code(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() or None
        return value


@dataclass(frozen=True, slots=True)
class PromptCompleteness:
    """Readiness of enabled definitions in one ordered pipeline group."""

    pipeline_group: str
    language_code: str | None
    required_count: int
    ready_count: int
    missing_asset_keys: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        return self.required_count > 0 and self.ready_count == self.required_count
