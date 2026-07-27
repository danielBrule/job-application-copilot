"""Synchronous Document A storage, upload, and activation."""

from __future__ import annotations

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import DOCUMENT_A_KEY, ReferenceAssetType
from job_application_copilot.errors import ExternalServiceError
from job_application_copilot.llm import OpenAIClient
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
    OpenAIClientFactory,
    RemoteReferenceOperation,
    remote_reference_operation,
)


class DocumentAProcessingError(ExternalServiceError):
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

        with remote_reference_operation(
            self.settings,
            self.client_factory,
            DocumentAProcessingError,
        ) as operation:
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
            return self._upload(candidate.version, operation)

    def _upload(self, version: int, operation: RemoteReferenceOperation) -> ReferenceAsset:
        try:
            return OpenAIFileUploadService(
                self.database,
                self.settings,
                operation.client,
            ).upload(DOCUMENT_A_KEY, version)
        except (
            OpenAIFileUploadError,
            OpenAIFileUploadNotAllowedError,
            ReferenceAssetIntegrityError,
            ReferenceAssetVersionNotFoundError,
        ) as error:
            raise DocumentAProcessingError(str(error)) from error
