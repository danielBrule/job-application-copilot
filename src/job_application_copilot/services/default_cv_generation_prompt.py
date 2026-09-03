"""Install packaged CV-generation prompts as private version 1 once."""

from importlib import resources
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.errors import ApplicationError, ApplicationOperationError
from job_application_copilot.repositories import Database
from job_application_copilot.services.prompt_service import PromptService

CV_STAGE_ONE_PROMPT_ASSET_KEY = "cv-generation-en-stage-1"
CV_STAGE_TWO_PROMPT_ASSET_KEY = "cv-generation-en-stage-2"
CV_STAGE_THREE_PROMPT_ASSET_KEY = "cv-generation-en-stage-3"
FRENCH_ADAPTATION_PROMPT_ASSET_KEY = "cv-generation-fr-extension-1"
DEFAULT_CV_STAGE_ONE_PROMPT_FILENAME = "cv-generation-en-stage-1-v1.txt"
DEFAULT_CV_STAGE_TWO_PROMPT_FILENAME = "cv-generation-en-stage-2-v1.txt"
DEFAULT_CV_STAGE_THREE_PROMPT_FILENAME = "cv-generation-en-stage-3-v1.txt"
DEFAULT_FRENCH_ADAPTATION_PROMPT_FILENAME = "cv-generation-fr-extension-1-v1.txt"


class DefaultCvGenerationPromptError(ApplicationOperationError):
    """Raised when the packaged generation prompt cannot be installed."""


class DefaultCvGenerationPromptService:
    """Seed generation prompts without replacing user versions."""

    def __init__(
        self, database: Database, settings: AppSettings, *, template_path: Path | None = None
    ) -> None:
        self.prompt_service = PromptService(database)
        self.template_path = template_path or _configured_template_path(settings)

    def ensure(self) -> bool:
        created_stage_one = self._ensure_prompt(
            CV_STAGE_ONE_PROMPT_ASSET_KEY, DEFAULT_CV_STAGE_ONE_PROMPT_FILENAME
        )
        created_stage_two = self._ensure_prompt(
            CV_STAGE_TWO_PROMPT_ASSET_KEY, DEFAULT_CV_STAGE_TWO_PROMPT_FILENAME
        )
        created_stage_three = self._ensure_prompt(
            CV_STAGE_THREE_PROMPT_ASSET_KEY, DEFAULT_CV_STAGE_THREE_PROMPT_FILENAME
        )
        created_french_adaptation = self._ensure_prompt(
            FRENCH_ADAPTATION_PROMPT_ASSET_KEY,
            DEFAULT_FRENCH_ADAPTATION_PROMPT_FILENAME,
        )
        return any(
            (
                created_stage_one,
                created_stage_two,
                created_stage_three,
                created_french_adaptation,
            )
        )

    def _ensure_prompt(self, asset_key: str, filename: str) -> bool:
        if self.prompt_service.list_versions(asset_key):
            return False
        try:
            prompt = self._read_template(filename)
        except (OSError, UnicodeError) as error:
            raise DefaultCvGenerationPromptError(
                "The packaged CV-generation prompt cannot be read."
            ) from error
        if not prompt.strip():
            raise DefaultCvGenerationPromptError("The packaged CV-generation prompt is blank.")
        try:
            created = self.prompt_service.save_text(asset_key, prompt)
        except ApplicationError as error:
            raise DefaultCvGenerationPromptError(
                "The default CV-generation prompt could not be installed safely."
            ) from error
        if created.version != 1:
            raise DefaultCvGenerationPromptError(
                "The default CV-generation prompt was not installed as version 1."
            )
        return True

    def _read_template(self, filename: str) -> str:
        if self.template_path is not None:
            return (self.template_path / filename).read_text(encoding="utf-8")
        return (
            resources.files("job_application_copilot.assets")
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )


def _configured_template_path(settings: AppSettings) -> Path | None:
    return settings.template_dir
