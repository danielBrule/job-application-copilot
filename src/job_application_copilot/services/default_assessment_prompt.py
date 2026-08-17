"""Install the packaged assessment prompt as private version 1 once."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.errors import ApplicationError, ApplicationOperationError
from job_application_copilot.repositories import Database
from job_application_copilot.services.prompt_service import PromptService

ASSESSMENT_PROMPT_ASSET_KEY = "assessment"
DEFAULT_ASSESSMENT_PROMPT_FILENAME = "assessment-prompt-v1.txt"


class DefaultAssessmentPromptError(ApplicationOperationError):
    """Raised when the packaged default assessment prompt cannot be installed."""


class DefaultAssessmentPromptService:
    """Seed v1 only when an installation has no retained assessment prompt."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        *,
        template_path: Path | None = None,
    ) -> None:
        self.prompt_service = PromptService(database)
        self.template_path = template_path or _configured_template_path(settings)

    def ensure(self) -> bool:
        """Install and activate the packaged v1, returning whether it was created."""

        if self.prompt_service.list_versions(ASSESSMENT_PROMPT_ASSET_KEY):
            return False
        try:
            prompt_text = self._read_template()
        except (OSError, UnicodeError) as error:
            raise DefaultAssessmentPromptError(
                "The packaged default assessment prompt cannot be read."
            ) from error
        if not prompt_text.strip():
            raise DefaultAssessmentPromptError("The packaged default assessment prompt is blank.")
        try:
            created = self.prompt_service.save_text(
                ASSESSMENT_PROMPT_ASSET_KEY,
                prompt_text,
            )
        except ApplicationError as error:
            raise DefaultAssessmentPromptError(
                "The default assessment prompt could not be installed safely."
            ) from error
        if created.version != 1:
            raise DefaultAssessmentPromptError(
                "The default assessment prompt was not installed as version 1."
            )
        return True

    def _read_template(self) -> str:
        if self.template_path is not None:
            return self.template_path.read_text(encoding="utf-8")
        return (
            resources.files("job_application_copilot.assets")
            .joinpath(DEFAULT_ASSESSMENT_PROMPT_FILENAME)
            .read_text(encoding="utf-8")
        )


def _configured_template_path(settings: AppSettings) -> Path | None:
    if settings.template_dir is None:
        return None
    return settings.template_dir / DEFAULT_ASSESSMENT_PROMPT_FILENAME
