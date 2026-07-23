"""Typed application settings loaded from the environment."""

from enum import StrEnum
from pathlib import Path
from typing import Literal

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


LogLevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class AppSettings(BaseSettings):
    """Validated settings for the local application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JAC_",
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = Path("data")
    database_path: Path = Field(
        default_factory=lambda data: data["data_dir"] / "database" / "job_application_copilot.db"
    )
    cv_folder: Path = Field(default_factory=lambda data: data["data_dir"] / "cvs")
    logs_folder: Path = Field(default_factory=lambda data: data["data_dir"] / "logs")
    reference_folder: Path = Field(default_factory=lambda data: data["data_dir"] / "reference")
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "JAC_OPENAI_API_KEY"),
    )
    assessment_worker_count: int = Field(default=1, ge=1, le=5)
    cv_worker_count: int = Field(default=1, ge=1, le=5)
    log_level: LogLevelName = "INFO"
    log_max_size_mb: int = Field(default=5, ge=1, le=100)
    log_backup_count: int = Field(default=5, ge=1, le=20)
    default_source: str = "LinkedIn"
    default_location: Location = Location.UK
    default_language: Language = Language.EN

    @property
    def document_a_folder(self) -> Path:
        """Directory containing private Document A versions."""

        return self.reference_folder / "document_a"

    @property
    def document_b_folder(self) -> Path:
        """Directory containing private Document B versions."""

        return self.reference_folder / "document_b"

    @property
    def templates_folder(self) -> Path:
        """Directory containing private CV templates."""

        return self.reference_folder / "templates"

    @property
    def french_examples_folder(self) -> Path:
        """Directory containing private French CV style examples."""

        return self.reference_folder / "examples"

    @property
    def assessment_prompts_folder(self) -> Path:
        """Directory containing private assessment prompt versions."""

        return self.reference_folder / "prompts" / "assessment"

    @property
    def english_generation_prompts_folder(self) -> Path:
        """Directory containing private English generation prompt versions."""

        return self.reference_folder / "prompts" / "generation" / "english"

    @property
    def french_generation_prompts_folder(self) -> Path:
        """Directory containing private French generation prompt versions."""

        return self.reference_folder / "prompts" / "generation" / "french"


def load_settings() -> AppSettings:
    """Load and validate settings from the environment and optional .env file."""

    return AppSettings()
