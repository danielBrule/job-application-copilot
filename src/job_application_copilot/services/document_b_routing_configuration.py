"""Safely validate and save the private editable Document B routing YAML."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from job_application_copilot.config import AppSettings
from job_application_copilot.config.document_b_routing import (
    RoutingConfigError,
    parse_document_b_routing_config,
)
from job_application_copilot.errors import ApplicationStorageError, ApplicationValidationError
from job_application_copilot.repositories import Database
from job_application_copilot.services.document_b_routing import (
    DocumentBRoutingError,
    DocumentBRoutingManifestService,
)
from job_application_copilot.services.document_b_sections import (
    DocumentBSectionError,
    DocumentBSectionRecord,
    DocumentBSectionService,
)


class DocumentBRoutingConfigurationError(ApplicationValidationError):
    """Raised when an authored routing configuration cannot be used safely."""


class DocumentBRoutingConfigurationStorageError(ApplicationStorageError):
    """Raised when validated routing YAML cannot be saved."""


class DocumentBRoutingConfigurationService:
    """Keep route-authoring validation outside the Streamlit Settings page."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.settings = settings
        self.routing = DocumentBRoutingManifestService(
            database,
            DocumentBSectionService(database, settings),
        )

    def load_text(self) -> str:
        """Return the currently editable private YAML."""

        try:
            return self.settings.document_b_routing_config_path.read_text(encoding="utf-8")
        except OSError as error:
            raise DocumentBRoutingConfigurationStorageError(
                "Document B routing configuration could not be read."
            ) from error

    def headings(self, version: int) -> tuple[DocumentBSectionRecord, ...]:
        """Return the exact heading catalogue for one retained version."""

        try:
            return self.routing.section_service.extract(version)
        except DocumentBSectionError as error:
            raise DocumentBRoutingConfigurationError(str(error)) from error

    def validate_and_save(self, version: int, content: str) -> None:
        """Reject invalid routes before atomically replacing the private YAML."""

        try:
            config = parse_document_b_routing_config(content)
            self.routing.validate_config(version, config)
        except (DocumentBSectionError, RoutingConfigError, DocumentBRoutingError) as error:
            raise DocumentBRoutingConfigurationError(str(error)) from error
        self._write_atomically(content)

    def _write_atomically(self, content: str) -> None:
        path = self.settings.document_b_routing_config_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        except OSError as error:
            if "temporary_path" in locals():
                temporary_path.unlink(missing_ok=True)
            raise DocumentBRoutingConfigurationStorageError(
                "Validated Document B routing configuration could not be saved."
            ) from error
