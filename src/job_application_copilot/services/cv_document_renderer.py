"""Load an active English template and save a populated local CV DOCX."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.documents.cv_renderer import render_cv_template
from job_application_copilot.domain import ENGLISH_CV_TEMPLATE_KEY, FinalCvOutput
from job_application_copilot.errors import ApplicationIntegrityError, ApplicationStorageError
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.reference_asset_repository import ReferenceAssetRepository
from job_application_copilot.services.cv_template_contract import CvTemplateContractService
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFileExistsError,
    ImmutableFilePathError,
    ImmutableFileWriteError,
    resolve_path_within,
    sha256_file_hash,
    write_bytes_exclusively,
)

WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class CvDocumentStorageError(ApplicationStorageError):
    """Raised when a rendered CV cannot be read or saved safely."""


class CvDocumentRendererService:
    """Render one final English CV to the configured local CV folder."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings
        self.template_contracts = CvTemplateContractService(database)

    def render(
        self,
        output: FinalCvOutput,
        *,
        company: str,
        generation_date: date | None = None,
    ) -> Path:
        """Populate the confirmed active template and create a non-overwriting DOCX output."""

        contract = self.template_contracts.active()
        contract.validate(output)
        template_content = self._active_template_content(contract.manifest.template_asset_id)
        rendered = render_cv_template(template_content, manifest=contract.manifest, output=output)
        return self._save_output(rendered, company, generation_date or date.today())

    def _save_output(self, rendered: bytes, company: str, generation_date: date) -> Path:
        try:
            self.settings.cv_folder.mkdir(parents=True, exist_ok=True)
        except (OSError, ImmutableFileWriteError) as error:
            raise CvDocumentStorageError(
                "Could not save the rendered CV in the configured CV folder."
            ) from error
        while True:
            destination = self._next_destination(company, generation_date)
            try:
                write_bytes_exclusively(destination, rendered)
            except ImmutableFileExistsError:
                continue
            except (OSError, ImmutableFileWriteError) as error:
                raise CvDocumentStorageError(
                    "Could not save the rendered CV in the configured CV folder."
                ) from error
            return destination

    def _active_template_content(self, template_asset_id: int) -> bytes:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).get_active(ENGLISH_CV_TEMPLATE_KEY)
            if asset is None or asset.id != template_asset_id:
                raise ApplicationIntegrityError(
                    "The active English CV template no longer matches its manifest."
                )
            if asset.file_path is None:
                raise ApplicationIntegrityError(
                    "The active English CV template has no retained local file path."
                )
            relative_path = asset.file_path
            file_hash = asset.file_hash
        try:
            path = resolve_path_within(
                self.settings.templates_folder, self.settings.reference_folder / relative_path
            )
            content = path.read_bytes()
        except (ImmutableFilePathError, OSError) as error:
            raise CvDocumentStorageError(
                "The active English CV template cannot be read safely."
            ) from error
        if sha256_file_hash(content) != file_hash:
            raise ApplicationIntegrityError(
                "The active English CV template failed integrity validation."
            )
        return content

    def _next_destination(self, company: str, generation_date: date) -> Path:
        safe_company = _safe_company_name(company)
        stem = f"resume - Daniel Brule - {generation_date.isoformat()} - {safe_company}"
        candidate = self.settings.cv_folder / f"{stem}.docx"
        suffix = 2
        while candidate.exists():
            candidate = self.settings.cv_folder / f"{stem} ({suffix}).docx"
            suffix += 1
        return candidate


def _safe_company_name(company: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", company).strip(" .-")
    if not sanitized:
        return "Company"
    stem, separator, extension = sanitized.partition(".")
    if stem.rstrip(" .").upper() in WINDOWS_RESERVED_NAMES:
        return f"{stem.rstrip(' .')}-company{separator}{extension}"
    return sanitized
