"""Install the packaged English stage-one prompt as private version 1 once."""

from importlib import resources
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.errors import ApplicationError, ApplicationOperationError
from job_application_copilot.repositories import Database
from job_application_copilot.services.prompt_service import PromptService

CV_STAGE_ONE_PROMPT_ASSET_KEY = "cv-generation-en-stage-1"
DEFAULT_CV_STAGE_ONE_PROMPT_FILENAME = "cv-generation-en-stage-1-v1.txt"


class DefaultCvGenerationPromptError(ApplicationOperationError):
    """Raised when the packaged generation prompt cannot be installed."""


class DefaultCvGenerationPromptService:
    """Seed the first English generation prompt without replacing user versions."""

    def __init__(
        self, database: Database, settings: AppSettings, *, template_path: Path | None = None
    ) -> None:
        self.prompt_service = PromptService(database, settings)
        self.template_path = template_path or _configured_template_path(settings)

    def ensure(self) -> bool:
        if self.prompt_service.list_versions(CV_STAGE_ONE_PROMPT_ASSET_KEY):
            return False
        try:
            prompt = self._read_template()
        except (OSError, UnicodeError) as error:
            raise DefaultCvGenerationPromptError(
                "The packaged CV-generation prompt cannot be read."
            ) from error
        if not prompt.strip():
            raise DefaultCvGenerationPromptError("The packaged CV-generation prompt is blank.")
        try:
            created = self.prompt_service.save_text(CV_STAGE_ONE_PROMPT_ASSET_KEY, prompt)
        except ApplicationError as error:
            raise DefaultCvGenerationPromptError(
                "The default CV-generation prompt could not be installed safely."
            ) from error
        if created.version != 1:
            raise DefaultCvGenerationPromptError(
                "The default CV-generation prompt was not installed as version 1."
            )
        return True

    def _read_template(self) -> str:
        if self.template_path is not None:
            return self.template_path.read_text(encoding="utf-8")
        return (
            resources.files("job_application_copilot.assets")
            .joinpath(DEFAULT_CV_STAGE_ONE_PROMPT_FILENAME)
            .read_text(encoding="utf-8")
        )


def _configured_template_path(settings: AppSettings) -> Path | None:
    return (
        None
        if settings.template_dir is None
        else settings.template_dir / DEFAULT_CV_STAGE_ONE_PROMPT_FILENAME
    )
