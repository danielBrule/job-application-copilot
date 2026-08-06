"""Validation and immutable local storage for reference DOCX assets."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.documents import validate_docx
from job_application_copilot.domain import (
    DOCUMENT_A_KEY,
    DOCUMENT_B_KEY,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.errors import (
    ApplicationNotFoundError,
    ApplicationStorageError,
    ApplicationValidationError,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFileExistsError,
    ImmutableFilePathError,
    ImmutableFileWriteError,
    relative_path_within,
    remove_created_file,
    sha256_file_hash,
    write_bytes_exclusively,
)

ASSET_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class DuplicateReferenceAssetError(ApplicationValidationError):
    """Raised when identical content already exists for a logical asset."""

    def __init__(
        self,
        asset_key: str,
        existing_version: int,
        *,
        existing_asset_key: str | None = None,
        existing_name: str | None = None,
    ) -> None:
        self.asset_key = asset_key
        self.existing_version = existing_version
        self.existing_asset_key = existing_asset_key or asset_key
        self.existing_name = existing_name
        if self.existing_asset_key == asset_key:
            message = (
                f"Reference asset '{asset_key}' already has identical content "
                f"in version {existing_version}."
            )
        else:
            existing_label = existing_name or self.existing_asset_key
            message = (
                f"The same content already exists in French example "
                f"'{existing_label}' version {existing_version}."
            )
        super().__init__(message)


class ReferenceAssetStorageError(ApplicationStorageError):
    """Raised when validated content cannot be stored safely."""


class UnsupportedReferenceAssetError(ApplicationValidationError):
    """Raised when an asset category is not handled by DOCX storage."""


class ReferenceExampleNotFoundError(ApplicationNotFoundError):
    """Raised when a French reference example cannot be removed or restored."""


class ReferenceAssetValidationError(ApplicationValidationError):
    """Raised when reference-asset input does not satisfy local boundary rules."""


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

        return self._store_version(
            filename=filename,
            content=content,
            asset_key=asset_key,
            asset_type=asset_type,
            name=name,
            language_code=language_code,
            activate_after_validation=False,
        )

    def replace(
        self,
        *,
        filename: str,
        content: bytes,
        asset_key: str,
        asset_type: ReferenceAssetType,
        name: str,
        language_code: str | None = None,
    ) -> ReferenceAsset:
        """Store a replacement and activate it when local validation is sufficient.

        Templates and reference examples are locally complete and become READY and
        active immediately. Documents remain inactive PENDING candidates until the
        later OpenAI workflow has completed.
        """

        return self._store_version(
            filename=filename,
            content=content,
            asset_key=asset_key,
            asset_type=asset_type,
            name=name,
            language_code=language_code,
            activate_after_validation=asset_type
            in {
                ReferenceAssetType.TEMPLATE,
                ReferenceAssetType.REFERENCE_EXAMPLE,
            },
        )

    def store_template_candidate(
        self, *, filename: str, content: bytes, asset_key: str, name: str, language_code: str
    ) -> ReferenceAsset:
        """Store a READY inactive template until its placeholder manifest is confirmed."""

        return self._store_version(
            filename=filename,
            content=content,
            asset_key=asset_key,
            asset_type=ReferenceAssetType.TEMPLATE,
            name=name,
            language_code=language_code,
            activate_after_validation=False,
            ready_when_stored=True,
        )

    def replace_french_example(
        self,
        *,
        filename: str,
        content: bytes,
        name: str,
    ) -> ReferenceAsset:
        """Add or version a French example whose stable key is derived from its name."""

        normalized_name, derived_key = self._french_example_identity(name)
        with self.database.session() as session:
            versions = ReferenceAssetRepository(session).list_by_type(
                ReferenceAssetType.REFERENCE_EXAMPLE,
                language_code="fr",
            )
            matching_keys = {
                version.asset_key
                for version in versions
                if self._normalize_example_name(version.name)
                == self._normalize_example_name(normalized_name)
            }
            if len(matching_keys) > 1:
                raise ReferenceAssetValidationError(
                    f"More than one French example already uses the name "
                    f"'{normalized_name}'. Remove the duplicate names first."
                )
            asset_key = next(iter(matching_keys), derived_key)
            conflicting_versions = [
                version
                for version in versions
                if version.asset_key == asset_key
                and self._normalize_example_name(version.name)
                != self._normalize_example_name(normalized_name)
            ]
            if conflicting_versions:
                raise ReferenceAssetValidationError(
                    f"French example name '{normalized_name}' conflicts with an "
                    "existing internal identity. Choose a more specific name."
                )
        return self.replace(
            filename=filename,
            content=content,
            asset_key=asset_key,
            asset_type=ReferenceAssetType.REFERENCE_EXAMPLE,
            name=normalized_name,
            language_code="fr",
        )

    def remove_french_example(self, asset_key: str) -> ReferenceAsset:
        """Remove an active French example from readiness without deleting history."""

        with self.database.session() as session:
            repository = ReferenceAssetRepository(session)
            active = repository.get_active(asset_key)
            if active is None or not self._is_french_example(active):
                raise ReferenceExampleNotFoundError(
                    f"Active French example '{asset_key}' does not exist."
                )
            active.is_active = False
            session.flush()
            return active

    def restore_french_example(self, asset_key: str) -> ReferenceAsset:
        """Restore the latest retained READY French-example version."""

        with self.database.session() as session:
            repository = ReferenceAssetRepository(session)
            current = repository.get_active(asset_key)
            if current is not None:
                if not self._is_french_example(current):
                    raise ReferenceExampleNotFoundError(
                        f"French example '{asset_key}' does not exist."
                    )
                return current

            target = next(
                (
                    version
                    for version in repository.list_versions(asset_key)
                    if self._is_french_example(version)
                    and version.processing_status is ReferenceAssetProcessingStatus.READY
                ),
                None,
            )
            if target is None:
                raise ReferenceExampleNotFoundError(
                    f"Restorable French example '{asset_key}' does not exist."
                )
            target.is_active = True
            session.flush()
            return target

    def _store_version(
        self,
        *,
        filename: str,
        content: bytes,
        asset_key: str,
        asset_type: ReferenceAssetType,
        name: str,
        language_code: str | None,
        activate_after_validation: bool,
        ready_when_stored: bool = False,
    ) -> ReferenceAsset:
        normalized_key = self._validate_asset_key(asset_key)
        normalized_name = name.strip()
        if not normalized_name:
            raise ReferenceAssetValidationError("Reference asset name must not be blank.")
        normalized_language = language_code.strip().lower() if language_code is not None else None
        if normalized_language == "":
            raise ReferenceAssetValidationError("Reference asset language must not be blank.")

        destination = self._destination_folder(asset_type, normalized_key)
        validate_docx(filename, content)
        file_hash = sha256_file_hash(content)
        stored_path: Path | None = None
        file_created = False

        try:
            with self.database.session() as session:
                repository = ReferenceAssetRepository(session)
                duplicate = (
                    repository.find_by_hash_for_type(asset_type, file_hash)
                    if asset_type is ReferenceAssetType.REFERENCE_EXAMPLE
                    else repository.find_by_hash(normalized_key, file_hash)
                )
                if duplicate is not None:
                    raise DuplicateReferenceAssetError(
                        normalized_key,
                        duplicate.version,
                        existing_asset_key=duplicate.asset_key,
                        existing_name=duplicate.name,
                    )

                version = repository.next_version(normalized_key)
                destination.mkdir(parents=True, exist_ok=True)
                stored_path = destination / f"{normalized_key}-v{version:04d}.docx"
                self._store_reference_asset_file(stored_path, content)
                file_created = True

                if activate_after_validation:
                    current = repository.get_active(normalized_key)
                    if current is not None:
                        current.is_active = False
                        session.flush()

                return repository.add(
                    ReferenceAsset(
                        asset_key=normalized_key,
                        asset_type=asset_type,
                        name=normalized_name,
                        language_code=normalized_language,
                        version=version,
                        file_path=self._relative_file_path(stored_path),
                        file_hash=file_hash,
                        is_active=activate_after_validation,
                        processing_status=(
                            ReferenceAssetProcessingStatus.READY
                            if activate_after_validation or ready_when_stored
                            else ReferenceAssetProcessingStatus.PENDING
                        ),
                    )
                )
        except Exception:
            remove_created_file(stored_path, created=file_created)
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
            return relative_path_within(self.settings.reference_folder, stored_path)
        except ImmutableFilePathError as error:
            raise ReferenceAssetStorageError(
                "Reference-asset folders must be located under the configured reference folder."
            ) from error

    @staticmethod
    def _validate_asset_key(asset_key: str) -> str:
        normalized_key = asset_key.strip()
        if not ASSET_KEY_PATTERN.fullmatch(normalized_key):
            raise ReferenceAssetValidationError(
                "Reference asset key must be a lowercase slug containing letters, "
                "numbers, and single hyphens."
            )
        return normalized_key

    @staticmethod
    def _french_example_identity(name: str) -> tuple[str, str]:
        normalized_name = " ".join(name.split())
        if not normalized_name:
            raise ReferenceAssetValidationError("French example name must not be blank.")

        ascii_name = (
            unicodedata.normalize("NFKD", normalized_name)
            .encode("ascii", "ignore")
            .decode("ascii")
            .casefold()
        )
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
        if not slug:
            raise ReferenceAssetValidationError(
                "French example name must contain at least one letter or number."
            )
        asset_key = f"french-example-{slug}"
        if len(asset_key) > 255:
            raise ReferenceAssetValidationError("French example name is too long.")
        return normalized_name, asset_key

    @staticmethod
    def _normalize_example_name(name: str) -> str:
        return " ".join(name.split()).casefold()

    @staticmethod
    def _is_french_example(asset: ReferenceAsset) -> bool:
        return (
            asset.asset_type is ReferenceAssetType.REFERENCE_EXAMPLE and asset.language_code == "fr"
        )

    @staticmethod
    def _store_reference_asset_file(path: Path, content: bytes) -> None:
        try:
            write_bytes_exclusively(path, content)
        except ImmutableFileExistsError as error:
            raise ReferenceAssetStorageError(
                f"Reference asset path already exists and will not be overwritten: {path}"
            ) from error
        except ImmutableFileWriteError as error:
            raise ReferenceAssetStorageError(
                f"Could not store the reference asset at {path}: {error.__cause__}"
            ) from error
