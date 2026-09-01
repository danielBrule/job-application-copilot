"""Safe local opening of active CV files on Windows."""

import os
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.errors import ApplicationNotFoundError, ApplicationOperationError
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFilePathError,
    resolve_path_within,
)


class CvFileOpenError(ApplicationOperationError):
    """Raised when a CV cannot be opened with the local default application."""


class CvFileMissingError(ApplicationNotFoundError):
    """Raised when a retained CV file is no longer available locally."""


class CvFileOpener:
    """Validate a shared-CV path before delegating to Windows."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def open(self, file_path: str | Path) -> None:
        try:
            path = resolve_path_within(self.settings.cv_folder, Path(file_path))
        except ImmutableFilePathError as error:
            raise CvFileOpenError("CV file is outside the configured shared CV folder.") from error
        if path.suffix.lower() != ".docx":
            raise CvFileOpenError("CV file must be a DOCX document.")
        if not path.is_file():
            raise CvFileMissingError("The CV file is missing. Upload or generate it again.")
        try:
            # Pass a string explicitly.  Streamlit retains ``file_path`` as text and
            # Windows shell association is more reliable when the launcher receives
            # the same concrete string representation.
            os.startfile(str(path), "open")  # Windows-only application.
        except OSError as error:
            raise CvFileOpenError(
                "The CV could not be opened with the Windows default application."
            ) from error
