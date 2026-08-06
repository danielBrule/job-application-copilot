"""Typed application settings loaded from the environment."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from job_application_copilot.domain import Language, Location

LogLevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
AssessmentReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]


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
    template_dir: Path | None = None
    document_b_routing_config_path: Path = Field(
        default_factory=lambda data: (
            data["reference_folder"] / "routing" / "document-b-lane-routes.yaml"
        )
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "JAC_OPENAI_API_KEY"),
    )
    assessment_model: str = "gpt-5.6-terra"
    assessment_reasoning_effort: AssessmentReasoningEffort = "medium"
    assessment_max_retries: int = Field(default=2, ge=0, le=5)
    assessment_retry_base_delay_seconds: float = Field(default=1.0, ge=0, le=30)
    assessment_worker_count: int = Field(default=1, ge=1, le=5)
    cv_generation_model: str = "gpt-5.6-terra"
    cv_generation_reasoning_effort: AssessmentReasoningEffort = "medium"
    cv_generation_max_retries: int = Field(default=2, ge=0, le=5)
    cv_worker_count: int = Field(default=1, ge=1, le=5)
    log_level: LogLevelName = "INFO"
    log_max_size_mb: int = Field(default=5, ge=1, le=100)
    log_backup_count: int = Field(default=5, ge=1, le=20)
    openai_vector_store_timeout_seconds: int = Field(default=300, ge=30, le=1_800)
    default_source: str = "LinkedIn"
    default_location: Location = Location.UK
    default_language: Language = Language.EN
    minimum_french_reference_examples: int = Field(default=2, ge=1)

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
    def prompts_folder(self) -> Path:
        """Root directory containing private prompt versions."""

        return self.reference_folder / "prompts"

    @property
    def routing_folder(self) -> Path:
        """Directory containing private Document B routing configuration."""

        return self.document_b_routing_config_path.parent

    @property
    def assessment_prompts_folder(self) -> Path:
        """Directory containing private assessment prompt versions."""

        return self.prompts_folder / "assessment"

    @property
    def english_generation_prompts_folder(self) -> Path:
        """Directory containing private English generation prompt versions."""

        return self.prompts_folder / "generation" / "english"

    @property
    def french_generation_prompts_folder(self) -> Path:
        """Directory containing private French generation prompt versions."""

        return self.prompts_folder / "generation" / "french"


def load_settings() -> AppSettings:
    """Load and validate settings from the environment and optional .env file."""

    return AppSettings()
