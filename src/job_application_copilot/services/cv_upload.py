"""Validated local storage for a user-provided active CV."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.documents import DocxValidationError, validate_docx
from job_application_copilot.domain import CvSource
from job_application_copilot.errors import ApplicationStorageError, ApplicationValidationError
from job_application_copilot.repositories import Database, JobRepository
from job_application_copilot.repositories.models import Cv
from job_application_copilot.services.cv_service import CvService
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFileExistsError,
    ImmutableFileWriteError,
    remove_created_file,
    write_bytes_exclusively,
)

WINDOWS_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_UPLOAD_NAME_ATTEMPTS = 100


class CvUploadValidationError(ApplicationValidationError):
    """Raised when a supplied CV upload is not a valid DOCX."""


class CvUploadStorageError(ApplicationStorageError):
    """Raised when a valid CV upload cannot be safely stored."""


class CvUploadService:
    """Copy one validated DOCX into the shared CV folder and make it review-ready."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings
        self.cv_service = CvService(database, settings)

    def upload(
        self,
        *,
        job_id: int,
        filename: str,
        content: bytes,
        recorded_at: datetime | None = None,
    ) -> Cv:
        """Validate, copy, and associate a user-provided DOCX with one job."""

        try:
            validate_docx(filename, content)
        except DocxValidationError as error:
            raise CvUploadValidationError(str(error)) from error

        with self.database.session() as session:
            job = JobRepository(session).require(job_id)
            language = job.language

        destination: Path | None = None
        created = False
        try:
            destination = self._store_file(job_id=job_id, filename=filename, content=content)
            created = True
            return self.cv_service.record_ready(
                job_id=job_id,
                source=CvSource.UPLOADED,
                language=language,
                file_path=destination,
                recorded_at=recorded_at,
            )
        except Exception:
            remove_created_file(destination, created=created)
            raise

    def _store_file(self, *, job_id: int, filename: str, content: bytes) -> Path:
        try:
            self.settings.cv_folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise CvUploadStorageError(
                f"Could not prepare the shared CV folder: {error}"
            ) from error
        if not self.settings.cv_folder.is_dir():
            raise CvUploadStorageError("The configured shared CV folder is not a directory.")

        stem = _safe_upload_stem(filename)
        for suffix in range(MAX_UPLOAD_NAME_ATTEMPTS):
            collision_suffix = "" if suffix == 0 else f" ({suffix + 1})"
            destination = (
                self.settings.cv_folder / f"uploaded - job-{job_id} - {stem}{collision_suffix}.docx"
            )
            try:
                write_bytes_exclusively(destination, content)
            except ImmutableFileExistsError:
                continue
            except ImmutableFileWriteError as error:
                raise CvUploadStorageError(
                    f"Could not store the uploaded CV: {error.__cause__}"
                ) from error
            return destination.resolve()
        raise CvUploadStorageError("Could not choose a unique filename for the uploaded CV.")


def _safe_upload_stem(filename: str) -> str:
    """Create a portable, non-blank stem from an untrusted upload filename."""

    basename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    stem = Path(basename).stem
    normalized = unicodedata.normalize("NFKC", stem)
    sanitized = WINDOWS_INVALID_FILENAME_CHARACTERS.sub("_", normalized)
    sanitized = " ".join(sanitized.split()).strip(". ")
    return (sanitized or "cv")[:160]
