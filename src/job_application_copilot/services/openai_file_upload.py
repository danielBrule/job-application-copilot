"""Upload authorised reference DOCX versions and persist OpenAI file IDs."""

from __future__ import annotations

import hashlib
from pathlib import Path

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
    UploadedOpenAIFile,
)
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)

logger = get_logger(__name__)
AUTHORISED_OPENAI_DOCUMENT_KEYS = frozenset({DOCUMENT_A_KEY, DOCUMENT_B_KEY})


class OpenAIFileUploadError(RuntimeError):
    """Raised when an authorised asset cannot complete its OpenAI upload."""


class OpenAIFileUploadNotAllowedError(ValueError):
    """Raised when an asset is not eligible for OpenAI file upload."""


class ReferenceAssetIntegrityError(RuntimeError):
    """Raised when retained local content no longer matches its stored metadata."""


class OpenAIFileUploadService:
    """Coordinate local asset metadata with the OpenAI Files API."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        client: OpenAIClient,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client

    def upload(self, asset_key: str, version: int) -> ReferenceAsset:
        """Upload one canonical document version or return its existing remote ID."""

        try:
            content, filename, existing = self._prepare_upload(asset_key, version)
        except ReferenceAssetIntegrityError as error:
            self._record_failure(asset_key, version, str(error))
            raise
        if existing is not None:
            return existing

        try:
            uploaded = self.client.upload_docx(filename=filename, content=content)
        except OpenAIClientError as error:
            self._record_failure(asset_key, version, str(error))
            raise OpenAIFileUploadError(str(error)) from error

        try:
            return self._record_success(asset_key, version, uploaded)
        except Exception as error:
            self._compensate_uploaded_file(uploaded.file_id)
            message = "The OpenAI file ID could not be saved locally."
            self._record_failure(asset_key, version, message)
            raise OpenAIFileUploadError(message) from error

    def _prepare_upload(
        self,
        asset_key: str,
        version: int,
    ) -> tuple[bytes, str, ReferenceAsset | None]:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(asset_key, version)
            self._validate_upload_target(asset)
            if asset.openai_file_id is not None:
                return b"", "", asset
            if asset.processing_status is ReferenceAssetProcessingStatus.READY and asset.is_active:
                raise OpenAIFileUploadNotAllowedError(
                    f"Reference asset '{asset_key}' version {version} is already READY "
                    "but has no OpenAI file ID."
                )

            # PROCESSING without a persisted remote ID means a previous local process may
            # have stopped during upload. This local, single-user workflow is safe to resume.
            stored_path = self._resolve_stored_path(asset.file_path)
            try:
                content = stored_path.read_bytes()
            except OSError as error:
                raise ReferenceAssetIntegrityError(
                    f"Stored reference asset '{asset_key}' version {version} cannot be read."
                ) from error
            actual_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
            if actual_hash != asset.file_hash:
                raise ReferenceAssetIntegrityError(
                    f"Stored reference asset '{asset_key}' version {version} "
                    "no longer matches its recorded hash."
                )

            asset.processing_status = ReferenceAssetProcessingStatus.PROCESSING
            asset.processing_error = None
            session.flush()
            return content, stored_path.name, None

    @staticmethod
    def _validate_upload_target(asset: ReferenceAsset) -> None:
        if (
            asset.asset_type is not ReferenceAssetType.DOCUMENT
            or asset.asset_key not in AUTHORISED_OPENAI_DOCUMENT_KEYS
        ):
            raise OpenAIFileUploadNotAllowedError(
                "Only canonical Document A and Document B versions may be uploaded to OpenAI."
            )

    def _resolve_stored_path(self, file_path: str) -> Path:
        reference_root = self.settings.reference_folder.resolve()
        stored_path = (reference_root / Path(file_path)).resolve()
        try:
            stored_path.relative_to(reference_root)
        except ValueError as error:
            raise ReferenceAssetIntegrityError(
                "The stored reference-asset path is outside the configured reference folder."
            ) from error
        if not stored_path.is_file():
            raise ReferenceAssetIntegrityError("The stored reference-asset file no longer exists.")
        return stored_path

    def _record_success(
        self,
        asset_key: str,
        version: int,
        uploaded: UploadedOpenAIFile,
    ) -> ReferenceAsset:
        with self.database.session() as session:
            repository = ReferenceAssetRepository(session)
            asset = repository.require_version(asset_key, version)
            if asset.openai_file_id is not None:
                if asset.openai_file_id != uploaded.file_id:
                    raise OpenAIFileUploadError(
                        f"Reference asset '{asset_key}' version {version} already has "
                        "a different OpenAI file ID."
                    )
                return asset

            asset.openai_file_id = uploaded.file_id
            asset.processing_error = None
            if asset.asset_key == DOCUMENT_A_KEY:
                current = repository.get_active(DOCUMENT_A_KEY)
                if current is not None and current.id != asset.id:
                    current.is_active = False
                    session.flush()
                asset.processing_status = ReferenceAssetProcessingStatus.READY
                asset.is_active = True
            else:
                asset.processing_status = ReferenceAssetProcessingStatus.PENDING
                asset.is_active = False
            session.flush()
            return asset

    def _record_failure(self, asset_key: str, version: int, message: str) -> None:
        try:
            with self.database.session() as session:
                asset = ReferenceAssetRepository(session).require_version(asset_key, version)
                if asset.openai_file_id is None:
                    asset.processing_status = ReferenceAssetProcessingStatus.FAILED
                    asset.processing_error = message[:2048]
                    asset.is_active = False
                    session.flush()
        except Exception:
            logger.exception(
                "openai_file_failure_status_not_saved asset_key=%s version=%s",
                asset_key,
                version,
            )

    def _compensate_uploaded_file(self, file_id: str) -> None:
        try:
            self.client.delete_file(file_id)
        except OpenAIClientError:
            logger.exception(
                "openai_file_compensation_failed file_id=%s",
                file_id,
            )
