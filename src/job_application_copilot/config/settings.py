"""Typed application settings loaded from the environment."""

from enum import StrEnum
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Location(StrEnum):
    """Supported job locations."""

    UK = "UK"
    FR = "FR"
    CH = "CH"


class Language(StrEnum):
    """Supported job and CV languages."""

    EN = "EN"
    FR = "FR"


class AppSettings(BaseSettings):
    """Validated settings for the local application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JAC_",
        extra="ignore",
    )

    data_dir: Path = Path("data")
    database_path: Path = Field(
        default_factory=lambda data: data["data_dir"] / "database" / "job_application_copilot.db"
    )
    cv_folder: Path = Field(default_factory=lambda data: data["data_dir"] / "cvs")
    reference_folder: Path = Field(default_factory=lambda data: data["data_dir"] / "reference")
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "JAC_OPENAI_API_KEY"),
    )
    assessment_worker_count: int = Field(default=1, ge=1, le=5)
    cv_worker_count: int = Field(default=1, ge=1, le=5)
    default_source: str = "LinkedIn"
    default_location: Location = Location.UK
    default_language: Language = Language.EN


def load_settings() -> AppSettings:
    """Load and validate settings from the environment and optional .env file."""

    return AppSettings()
