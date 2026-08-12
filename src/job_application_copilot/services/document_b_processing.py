"""Synchronous Document B upload, indexing, validation, and activation."""

from __future__ import annotations

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.errors import ExternalServiceError
from job_application_copilot.llm import OpenAIClient
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
    ReferenceAssetVersionNotFoundError,
)
from job_application_copilot.services.document_b_progress import (
    DocumentBProcessingProgress,
    DocumentBProgressReporter,
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
    DuplicateReferenceAssetError,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.remote_reference_operation import (
    OpenAIClientFactory,
    RemoteReferenceOperation,
    remote_reference_operation,
)


class DocumentBProcessingError(ExternalServiceError):
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

    def process(
        self,
        version: int,
        *,
        progress: DocumentBProgressReporter | None = None,
    ) -> ReferenceAsset:
        """Upload, index, validate, and activate one Document B candidate."""

        with remote_reference_operation(
            self.settings,
            self.client_factory,
            DocumentBProcessingError,
        ) as operation:
            return self._process(version, operation, progress=progress)

    def replace_and_process(self, *, filename: str, content: bytes) -> ReferenceAsset:
        """Store a new Document B version, then process and activate it."""

        with remote_reference_operation(
            self.settings,
            self.client_factory,
            DocumentBProcessingError,
        ) as operation:
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
            except DuplicateReferenceAssetError as error:
                failed_candidate = self._failed_duplicate_candidate(error)
                if failed_candidate is None:
                    raise
                candidate = failed_candidate
            return self._process(candidate.version, operation)

    def _failed_duplicate_candidate(
        self,
        error: DuplicateReferenceAssetError,
    ) -> ReferenceAsset | None:
        """Reuse an immutable failed Document B candidate on an identical re-upload."""

        with self.database.session() as session:
            candidate = ReferenceAssetRepository(session).require_version(
                DOCUMENT_B_KEY,
                error.existing_version,
            )
            if (
                not candidate.is_active
                and candidate.processing_status is ReferenceAssetProcessingStatus.FAILED
            ):
                return candidate
        return None

    def _process(
        self,
        version: int,
        operation: RemoteReferenceOperation,
        *,
        progress: DocumentBProgressReporter | None = None,
    ) -> ReferenceAsset:
        client = operation.client
        try:
            _report(progress, "uploading", "Ensuring Document B is uploaded to OpenAI.")
            OpenAIFileUploadService(
                self.database,
                self.settings,
                client,
            ).upload(DOCUMENT_B_KEY, version)
            return DocumentBVectorStoreService(
                self.database,
                self.settings,
                client,
            ).process(DOCUMENT_B_KEY, version, progress=progress)
        except (
            DocumentBVectorStoreError,
            DocumentBVectorStoreNotAllowedError,
            OpenAIFileUploadError,
            OpenAIFileUploadNotAllowedError,
            ReferenceAssetIntegrityError,
            ReferenceAssetVersionNotFoundError,
        ) as error:
            raise DocumentBProcessingError(str(error)) from error


def _report(
    reporter: DocumentBProgressReporter | None,
    stage: str,
    message: str,
) -> None:
    if reporter is not None:
        reporter(DocumentBProcessingProgress(stage=stage, message=message))
