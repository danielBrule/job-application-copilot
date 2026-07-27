"""Synchronous Document B upload, indexing, validation, and activation."""

from __future__ import annotations

from collections.abc import Callable

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    ReferenceAssetType,
)
from job_application_copilot.llm import (
    OpenAIClient,
    OpenAIConfigurationError,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetVersionNotFoundError,
)
from job_application_copilot.services.document_b_vector_store import (
    DocumentBVectorStoreError,
    DocumentBVectorStoreNotAllowedError,
    DocumentBVectorStoreService,
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


class DocumentBProcessingError(RuntimeError):
    """Safe failure from the complete user-triggered Document B workflow."""


class DocumentBProcessingService:
    """Run the existing OpenAI upload and vector-store services in order."""

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

    def process(self, version: int) -> ReferenceAsset:
        """Upload, index, validate, and activate one Document B candidate."""

        self._acquire_processing_lock()
        try:
            return self._process(version)
        finally:
            release_remote_reference_operation()

    def replace_and_process(self, *, filename: str, content: bytes) -> ReferenceAsset:
        """Store a new Document B version, then process and activate it."""

        self._acquire_processing_lock()
        try:
            candidate = ReferenceAssetStorageService(
                self.database,
                self.settings,
            ).replace(
                filename=filename,
                content=content,
                asset_key=DOCUMENT_B_KEY,
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document B",
            )
            return self._process(candidate.version)
        finally:
            release_remote_reference_operation()

    @staticmethod
    def _acquire_processing_lock() -> None:
        if not try_acquire_remote_reference_operation():
            raise DocumentBProcessingError(
                "Another OpenAI reference-asset operation is already running. "
                "Wait for it to finish."
            )

    def _process(self, version: int) -> ReferenceAsset:
        try:
            client = self.client_factory(self.settings)
        except OpenAIConfigurationError as error:
            raise DocumentBProcessingError(str(error)) from error

        try:
            OpenAIFileUploadService(
                self.database,
                self.settings,
                client,
            ).upload(DOCUMENT_B_KEY, version)
            return DocumentBVectorStoreService(
                self.database,
                self.settings,
                client,
            ).process(DOCUMENT_B_KEY, version)
        except (
            DocumentBVectorStoreError,
            DocumentBVectorStoreNotAllowedError,
            OpenAIFileUploadError,
            OpenAIFileUploadNotAllowedError,
            ReferenceAssetIntegrityError,
            ReferenceAssetVersionNotFoundError,
        ) as error:
            raise DocumentBProcessingError(str(error)) from error
        finally:
            client.close()
