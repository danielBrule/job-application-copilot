"""Explicit cleanup of tracked OpenAI resources for inactive local assets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    DOCUMENT_A_KEY,
    DOCUMENT_B_KEY,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.llm import (
    OpenAIClient,
    OpenAIClientError,
    OpenAIConfigurationError,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
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
from job_application_copilot.services.remote_reference_operation import (
    release_remote_reference_operation,
    try_acquire_remote_reference_operation,
)

REMOTE_DOCUMENT_KEYS = frozenset({DOCUMENT_A_KEY, DOCUMENT_B_KEY})
RemoteClientFactory = Callable[[AppSettings], OpenAIClient]


class ReferenceAssetRemoteCleanupError(RuntimeError):
    """Safe failure from explicit inactive-resource cleanup."""


class ReferenceAssetRemoteCleanupNotAllowedError(ValueError):
    """Raised when a reference version is not safe to clean."""


class ReferenceAssetRemoteRestoreError(RuntimeError):
    """Safe failure from restoring one retained local reference version."""


class ReferenceAssetRemoteRestoreNotAllowedError(ValueError):
    """Raised when a retained version is not eligible for restoration."""


@dataclass(frozen=True, slots=True)
class InactiveRemoteAsset:
    """Presentation-neutral cleanup candidate backed by retained local metadata."""

    asset_key: str
    name: str
    version: int
    processing_status: ReferenceAssetProcessingStatus
    file_path: str
    openai_file_id: str | None
    openai_vector_store_id: str | None
    openai_vector_store_usage_bytes: int | None


@dataclass(frozen=True, slots=True)
class ReferenceAssetRemoteCleanupResult:
    """Remote resources removed for one retained local version."""

    asset_key: str
    version: int
    vector_store_deleted: bool
    file_deleted: bool


class ReferenceAssetRemoteCleanupService:
    """List and explicitly remove tracked remote resources from inactive assets."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        *,
        client_factory: RemoteClientFactory = OpenAIClient.from_settings,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client_factory = client_factory

    def list_candidates(self) -> tuple[InactiveRemoteAsset, ...]:
        """Return inactive, non-processing versions that still own remote resources."""

        with self.database.session() as session:
            assets = ReferenceAssetRepository(session).list_inactive_with_remote_resources()
            return tuple(_summary(asset) for asset in assets)

    def list_restorable_versions(self) -> tuple[InactiveRemoteAsset, ...]:
        """Return retained inactive documents that can rebuild their remote state."""

        with self.database.session() as session:
            assets = ReferenceAssetRepository(
                session
            ).list_inactive_documents_without_remote_resources(
                asset_keys=REMOTE_DOCUMENT_KEYS,
            )
            return tuple(_summary(asset) for asset in assets)

    def cleanup(self, asset_key: str, version: int) -> ReferenceAssetRemoteCleanupResult:
        """Delete one inactive version's tracked store and file, preserving local state."""

        if not try_acquire_remote_reference_operation():
            raise ReferenceAssetRemoteCleanupError(
                "Another OpenAI reference-asset operation is already running. "
                "Wait for it to finish."
            )
        try:
            return self._cleanup_exclusively(asset_key, version)
        finally:
            release_remote_reference_operation()

    def _cleanup_exclusively(
        self,
        asset_key: str,
        version: int,
    ) -> ReferenceAssetRemoteCleanupResult:
        candidate = self._prepare(asset_key, version)
        try:
            cleaner = self.client_factory(self.settings)
        except OpenAIConfigurationError as error:
            raise ReferenceAssetRemoteCleanupError(str(error)) from error

        store_deleted = False
        file_deleted = False
        try:
            if candidate.openai_vector_store_id is not None:
                cleaner.delete_vector_store(candidate.openai_vector_store_id)
                self._clear_vector_store(
                    asset_key,
                    version,
                    candidate.openai_vector_store_id,
                )
                store_deleted = True

            if candidate.openai_file_id is not None:
                cleaner.delete_file(candidate.openai_file_id)
                self._clear_file(
                    asset_key,
                    version,
                    candidate.openai_file_id,
                )
                file_deleted = True
        except OpenAIClientError as error:
            raise ReferenceAssetRemoteCleanupError(str(error)) from error
        finally:
            cleaner.close()

        return ReferenceAssetRemoteCleanupResult(
            asset_key=asset_key,
            version=version,
            vector_store_deleted=store_deleted,
            file_deleted=file_deleted,
        )

    def restore(self, asset_key: str, version: int) -> ReferenceAsset:
        """Rebuild remote resources and atomically activate one retained local version."""

        if not try_acquire_remote_reference_operation():
            raise ReferenceAssetRemoteRestoreError(
                "Another OpenAI reference-asset operation is already running. "
                "Wait for it to finish."
            )
        try:
            return self._restore_exclusively(asset_key, version)
        finally:
            release_remote_reference_operation()

    def _restore_exclusively(self, asset_key: str, version: int) -> ReferenceAsset:
        self._prepare_restoration(asset_key, version)
        try:
            client = self.client_factory(self.settings)
        except OpenAIConfigurationError as error:
            raise ReferenceAssetRemoteRestoreError(str(error)) from error

        try:
            uploaded = OpenAIFileUploadService(
                self.database,
                self.settings,
                client,
            ).upload(asset_key, version)
            if asset_key == DOCUMENT_A_KEY:
                return uploaded
            return DocumentBVectorStoreService(
                self.database,
                self.settings,
                client,
            ).process(asset_key, version)
        except (
            DocumentBVectorStoreError,
            DocumentBVectorStoreNotAllowedError,
            OpenAIFileUploadError,
            OpenAIFileUploadNotAllowedError,
            ReferenceAssetIntegrityError,
            ReferenceAssetVersionNotFoundError,
        ) as error:
            raise ReferenceAssetRemoteRestoreError(str(error)) from error
        finally:
            client.close()

    def _prepare(self, asset_key: str, version: int) -> InactiveRemoteAsset:
        try:
            with self.database.session() as session:
                repository = ReferenceAssetRepository(session)
                asset = repository.require_version(asset_key, version)
                self._validate_candidate(repository, asset)
                return _summary(asset)
        except ReferenceAssetVersionNotFoundError:
            raise

    def _prepare_restoration(self, asset_key: str, version: int) -> None:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(asset_key, version)
            if (
                asset.asset_key not in REMOTE_DOCUMENT_KEYS
                or asset.asset_type is not ReferenceAssetType.DOCUMENT
            ):
                raise ReferenceAssetRemoteRestoreNotAllowedError(
                    "Only retained Document A and Document B versions may be restored."
                )
            if asset.is_active:
                raise ReferenceAssetRemoteRestoreNotAllowedError(
                    f"Reference asset '{asset_key}' version {version} is already active."
                )
            if asset.processing_status is ReferenceAssetProcessingStatus.PROCESSING:
                raise ReferenceAssetRemoteRestoreNotAllowedError(
                    f"Reference asset '{asset_key}' version {version} is processing."
                )
            if asset.openai_file_id is not None or asset.openai_vector_store_id is not None:
                raise ReferenceAssetRemoteRestoreNotAllowedError(
                    f"Reference asset '{asset_key}' version {version} still has "
                    "tracked OpenAI resources."
                )

    @staticmethod
    def _validate_candidate(
        repository: ReferenceAssetRepository,
        asset: ReferenceAsset,
    ) -> None:
        if asset.is_active:
            raise ReferenceAssetRemoteCleanupNotAllowedError(
                f"Reference asset '{asset.asset_key}' version {asset.version} is active."
            )
        if asset.processing_status is ReferenceAssetProcessingStatus.PROCESSING:
            raise ReferenceAssetRemoteCleanupNotAllowedError(
                f"Reference asset '{asset.asset_key}' version {asset.version} is processing."
            )
        if asset.openai_file_id is None and asset.openai_vector_store_id is None:
            raise ReferenceAssetRemoteCleanupNotAllowedError(
                f"Reference asset '{asset.asset_key}' version {asset.version} "
                "has no tracked OpenAI resources."
            )
        if repository.has_active_remote_reference(
            openai_file_id=asset.openai_file_id,
            openai_vector_store_id=asset.openai_vector_store_id,
        ):
            raise ReferenceAssetRemoteCleanupNotAllowedError(
                "An active reference asset uses one of the selected OpenAI resources."
            )

    def _clear_vector_store(
        self,
        asset_key: str,
        version: int,
        expected_vector_store_id: str,
    ) -> None:
        try:
            with self.database.session() as session:
                repository = ReferenceAssetRepository(session)
                asset = repository.require_version(asset_key, version)
                self._validate_still_inactive(asset)
                if asset.openai_vector_store_id != expected_vector_store_id:
                    raise ReferenceAssetRemoteCleanupError(
                        "The local vector-store association changed during cleanup."
                    )
                asset.openai_vector_store_id = None
                asset.openai_vector_store_usage_bytes = None
                session.flush()
        except ReferenceAssetRemoteCleanupNotAllowedError:
            raise
        except ReferenceAssetRemoteCleanupError:
            raise
        except Exception as error:
            raise ReferenceAssetRemoteCleanupError(
                "The vector store was deleted but its local association could not be cleared. "
                "Retry cleanup."
            ) from error

    def _clear_file(
        self,
        asset_key: str,
        version: int,
        expected_file_id: str,
    ) -> None:
        try:
            with self.database.session() as session:
                asset = ReferenceAssetRepository(session).require_version(asset_key, version)
                self._validate_still_inactive(asset)
                if asset.openai_file_id != expected_file_id:
                    raise ReferenceAssetRemoteCleanupError(
                        "The local OpenAI-file association changed during cleanup."
                    )
                asset.openai_file_id = None
                session.flush()
        except ReferenceAssetRemoteCleanupNotAllowedError:
            raise
        except ReferenceAssetRemoteCleanupError:
            raise
        except Exception as error:
            raise ReferenceAssetRemoteCleanupError(
                "The OpenAI file was deleted but its local association could not be cleared. "
                "Retry cleanup."
            ) from error

    @staticmethod
    def _validate_still_inactive(asset: ReferenceAsset) -> None:
        if asset.is_active:
            raise ReferenceAssetRemoteCleanupNotAllowedError(
                "The selected reference asset became active during cleanup."
            )


def _summary(asset: ReferenceAsset) -> InactiveRemoteAsset:
    return InactiveRemoteAsset(
        asset_key=asset.asset_key,
        name=asset.name,
        version=asset.version,
        processing_status=asset.processing_status,
        file_path=asset.file_path,
        openai_file_id=asset.openai_file_id,
        openai_vector_store_id=asset.openai_vector_store_id,
        openai_vector_store_usage_bytes=asset.openai_vector_store_usage_bytes,
    )
