"""Validation and immutable local storage for reference DOCX assets."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.documents import validate_docx
from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)

ASSET_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DOCUMENT_A_KEY = "document-a"
DOCUMENT_B_KEY = "document-b"


class DuplicateReferenceAssetError(ValueError):
    """Raised when identical content already exists for a logical asset."""

    def __init__(self, asset_key: str, existing_version: int) -> None:
        self.asset_key = asset_key
        self.existing_version = existing_version
        super().__init__(
            f"Reference asset '{asset_key}' already has identical content "
            f"in version {existing_version}."
        )


class ReferenceAssetStorageError(RuntimeError):
    """Raised when validated content cannot be stored safely."""


class UnsupportedReferenceAssetError(ValueError):
    """Raised when an asset category is not handled by DOCX storage."""


class ReferenceAssetStorageService:
    """Store validated DOCX content and metadata as immutable versions."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings

    def store(
        self,
        *,
        filename: str,
        content: bytes,
        asset_key: str,
        asset_type: ReferenceAssetType,
        name: str,
        language_code: str | None = None,
    ) -> ReferenceAsset:
        """Validate and persist one new inactive, pending DOCX version."""

        normalized_key = self._validate_asset_key(asset_key)
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Reference asset name must not be blank.")
        normalized_language = language_code.strip().lower() if language_code is not None else None
        if normalized_language == "":
            raise ValueError("Reference asset language must not be blank.")

        destination = self._destination_folder(asset_type, normalized_key)
        validate_docx(filename, content)
        file_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
        stored_path: Path | None = None
        file_created = False

        try:
            with self.database.session() as session:
                repository = ReferenceAssetRepository(session)
                duplicate = repository.find_by_hash(normalized_key, file_hash)
                if duplicate is not None:
                    raise DuplicateReferenceAssetError(normalized_key, duplicate.version)

                version = repository.next_version(normalized_key)
                destination.mkdir(parents=True, exist_ok=True)
                stored_path = destination / f"{normalized_key}-v{version:04d}.docx"
                self._write_exclusively(stored_path, content)
                file_created = True

                return repository.add(
                    ReferenceAsset(
                        asset_key=normalized_key,
                        asset_type=asset_type,
                        name=normalized_name,
                        language_code=normalized_language,
                        version=version,
                        file_path=self._relative_file_path(stored_path),
                        file_hash=file_hash,
                        is_active=False,
                        processing_status=ReferenceAssetProcessingStatus.PENDING,
                    )
                )
        except Exception:
            if stored_path is not None and file_created:
                stored_path.unlink(missing_ok=True)
            raise

    def _destination_folder(
        self,
        asset_type: ReferenceAssetType,
        asset_key: str,
    ) -> Path:
        if asset_type is ReferenceAssetType.DOCUMENT:
            if asset_key == DOCUMENT_A_KEY:
                return self.settings.document_a_folder
            if asset_key == DOCUMENT_B_KEY:
                return self.settings.document_b_folder
            raise UnsupportedReferenceAssetError(
                "DOCX document assets must use the key 'document-a' or 'document-b'."
            )
        if asset_type is ReferenceAssetType.TEMPLATE:
            return self.settings.templates_folder
        if asset_type is ReferenceAssetType.REFERENCE_EXAMPLE:
            return self.settings.french_examples_folder
        raise UnsupportedReferenceAssetError(
            f"Asset type {asset_type.value} is not stored as DOCX."
        )

    def _relative_file_path(self, stored_path: Path) -> str:
        try:
            return stored_path.relative_to(self.settings.reference_folder).as_posix()
        except ValueError as error:
            raise ReferenceAssetStorageError(
                "Reference-asset folders must be located under the configured reference folder."
            ) from error

    @staticmethod
    def _validate_asset_key(asset_key: str) -> str:
        normalized_key = asset_key.strip()
        if not ASSET_KEY_PATTERN.fullmatch(normalized_key):
            raise ValueError(
                "Reference asset key must be a lowercase slug containing letters, "
                "numbers, and single hyphens."
            )
        return normalized_key

    @staticmethod
    def _write_exclusively(path: Path, content: bytes) -> None:
        try:
            with path.open("xb") as target:
                target.write(content)
        except FileExistsError as error:
            raise ReferenceAssetStorageError(
                f"Reference asset path already exists and will not be overwritten: {path}"
            ) from error
        except OSError as error:
            path.unlink(missing_ok=True)
            raise ReferenceAssetStorageError(
                f"Could not store the reference asset at {path}: {error}"
            ) from error
