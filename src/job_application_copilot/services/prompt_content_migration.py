"""One-time import of legacy file-backed prompts into SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import ReferenceAssetType
from job_application_copilot.errors import ApplicationOperationError
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import PromptContent, ReferenceAsset
from job_application_copilot.repositories.prompt_content_repository import (
    PromptContentRepository,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFilePathError,
    resolve_path_within,
    sha256_file_hash,
)


class PromptContentMigrationError(ApplicationOperationError):
    """Raised when retained legacy prompt text cannot be migrated safely."""


@dataclass(frozen=True, slots=True)
class PromptContentMigrationResult:
    """Observed work from one idempotent legacy prompt migration attempt."""

    imported_version_count: int
    removed_legacy_file_count: int


@dataclass(frozen=True, slots=True)
class _LegacyPromptFile:
    """One validated legacy prompt file eligible for cleanup."""

    reference_asset_id: int
    asset_key: str
    version: int
    relative_path: str


class PromptContentMigrationService:
    """Copy verified prompt history into SQLite before removing legacy files."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings

    def migrate(self) -> PromptContentMigrationResult:
        """Import every historical prompt version and remove only copied legacy files."""

        imported_version_count = self._import_missing_contents()
        removed_legacy_file_count = self._remove_legacy_files()
        return PromptContentMigrationResult(
            imported_version_count=imported_version_count,
            removed_legacy_file_count=removed_legacy_file_count,
        )

    def _import_missing_contents(self) -> int:
        imported_version_count = 0
        with self.database.session() as session:
            # UI and worker startup can both request this migration. Acquiring SQLite's
            # write lock before checking rows prevents their read-then-insert paths from
            # racing while still rolling every imported version back on validation failure.
            session.execute(text("BEGIN IMMEDIATE"))
            assets = ReferenceAssetRepository(session).list_by_type(ReferenceAssetType.PROMPT)
            contents = PromptContentRepository(session)
            for asset in assets:
                stored = contents.get(asset.id)
                if stored is not None:
                    self._validate_content(asset, stored.content)
                    continue

                content_text = self._read_legacy_text(asset)
                contents.add(PromptContent(reference_asset_id=asset.id, content=content_text))
                session.flush()
                stored = contents.get(asset.id)
                if stored is None:
                    raise PromptContentMigrationError(
                        f"Prompt '{asset.asset_key}' version {asset.version} could not be retained."
                    )
                self._validate_content(asset, stored.content)
                imported_version_count += 1
        return imported_version_count

    def _remove_legacy_files(self) -> int:
        with self.database.session() as session:
            assets = ReferenceAssetRepository(session).list_by_type(ReferenceAssetType.PROMPT)
            contents = PromptContentRepository(session)
            candidates = []
            for asset in assets:
                if asset.file_path is None:
                    continue
                stored = contents.get(asset.id)
                if stored is None:
                    raise PromptContentMigrationError(
                        f"Prompt '{asset.asset_key}' version {asset.version} has no retained text."
                    )
                self._validate_content(asset, stored.content)
                candidates.append(
                    _LegacyPromptFile(
                        reference_asset_id=asset.id,
                        asset_key=asset.asset_key,
                        version=asset.version,
                        relative_path=asset.file_path,
                    )
                )

        removed_legacy_file_count = 0
        for candidate in candidates:
            if self._remove_legacy_file(candidate):
                removed_legacy_file_count += 1
            self._clear_legacy_path(candidate)
        return removed_legacy_file_count

    def _read_legacy_text(self, asset: ReferenceAsset) -> str:
        if asset.file_path is None:
            raise PromptContentMigrationError(
                f"Prompt '{asset.asset_key}' version {asset.version} has no retained text or file."
            )
        path = self._resolve_legacy_path(asset.file_path, asset)
        try:
            content = path.read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise PromptContentMigrationError(
                f"Prompt '{asset.asset_key}' version {asset.version} cannot be read safely."
            ) from error
        self._validate_content(asset, text)
        return text

    def _remove_legacy_file(self, candidate: _LegacyPromptFile) -> bool:
        path = self._resolve_legacy_path(candidate.relative_path, candidate)
        if not path.exists():
            return False
        if not path.is_file():
            raise PromptContentMigrationError(
                f"Legacy prompt '{candidate.asset_key}' version {candidate.version} is not a file."
            )
        try:
            path.unlink()
        except OSError as error:
            raise PromptContentMigrationError(
                f"Legacy prompt '{candidate.asset_key}' version {candidate.version} "
                "could not be removed after migration."
            ) from error
        return True

    def _clear_legacy_path(self, candidate: _LegacyPromptFile) -> None:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(
                candidate.asset_key,
                candidate.version,
            )
            if (
                asset.id != candidate.reference_asset_id
                or asset.asset_type is not ReferenceAssetType.PROMPT
            ):
                raise PromptContentMigrationError(
                    f"Prompt '{candidate.asset_key}' version {candidate.version} changed during migration."
                )
            stored = PromptContentRepository(session).get(asset.id)
            if stored is None:
                raise PromptContentMigrationError(
                    f"Prompt '{candidate.asset_key}' version {candidate.version} has no retained text."
                )
            self._validate_content(asset, stored.content)
            if asset.file_path == candidate.relative_path:
                asset.file_path = None
                session.flush()

    def _resolve_legacy_path(
        self,
        relative_path: str,
        asset: ReferenceAsset | _LegacyPromptFile,
    ) -> Path:
        path = self.settings.reference_folder / relative_path
        try:
            resolve_path_within(self.settings.legacy_prompts_folder, path)
        except ImmutableFilePathError as error:
            raise PromptContentMigrationError(
                f"Prompt '{asset.asset_key}' version {asset.version} has an unsafe legacy path."
            ) from error
        return path

    @staticmethod
    def _validate_content(asset: ReferenceAsset, text: str) -> None:
        if not text.strip():
            raise PromptContentMigrationError(
                f"Prompt '{asset.asset_key}' version {asset.version} is blank."
            )
        if sha256_file_hash(text.encode("utf-8")) != asset.file_hash:
            raise PromptContentMigrationError(
                f"Prompt '{asset.asset_key}' version {asset.version} no longer matches "
                "its recorded hash."
            )
