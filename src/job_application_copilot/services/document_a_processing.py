"""Synchronous Document A storage, upload, and activation."""

from __future__ import annotations

from collections.abc import Callable

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import DOCUMENT_A_KEY, ReferenceAssetType
from job_application_copilot.llm import OpenAIClient, OpenAIConfigurationError
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetVersionNotFoundError,
)
from job_application_copilot.services.openai_file_upload import (
    OpenAIFileUploadError,
    OpenAIFileUploadNotAllowedError,
    OpenAIFileUploadService,
    ReferenceAssetIntegrityError,
)
from job_application_copilot.services.reference_asset_storage import (
    ReferenceAssetStorageService,
)
from job_application_copilot.services.remote_reference_operation import (
    release_remote_reference_operation,
    try_acquire_remote_reference_operation,
)

OpenAIClientFactory = Callable[[AppSettings], OpenAIClient]


class DocumentAProcessingError(RuntimeError):
    """Safe failure from the complete user-triggered Document A workflow."""


class DocumentAProcessingService:
    """Store, upload, and activate a Document A replacement in one workflow."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        *,
        client_factory: OpenAIClientFactory = OpenAIClient.from_settings,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client_factory = client_factory

    def replace_and_process(self, *, filename: str, content: bytes) -> ReferenceAsset:
        """Store a new Document A version, then upload and activate it."""

        if not try_acquire_remote_reference_operation():
            raise DocumentAProcessingError(
                "Another OpenAI reference-asset operation is already running. "
                "Wait for it to finish."
            )
        try:
            candidate = ReferenceAssetStorageService(
                self.database,
                self.settings,
            ).replace(
                filename=filename,
                content=content,
                asset_key=DOCUMENT_A_KEY,
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document A",
            )
            return self._upload(candidate.version)
        finally:
            release_remote_reference_operation()

    def _upload(self, version: int) -> ReferenceAsset:
        try:
            client = self.client_factory(self.settings)
        except OpenAIConfigurationError as error:
            raise DocumentAProcessingError(str(error)) from error

        try:
            return OpenAIFileUploadService(
                self.database,
                self.settings,
                client,
            ).upload(DOCUMENT_A_KEY, version)
        except (
            OpenAIFileUploadError,
            OpenAIFileUploadNotAllowedError,
            ReferenceAssetIntegrityError,
            ReferenceAssetVersionNotFoundError,
        ) as error:
            raise DocumentAProcessingError(str(error)) from error
        finally:
            client.close()
