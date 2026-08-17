"""Development-only reset of stored reference-asset versions."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from job_application_copilot.config import AppSettings, load_settings
from job_application_copilot.domain import ReferenceAssetType
from job_application_copilot.llm import OpenAIClient, OpenAIRemoteCleanupOperations
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.local_directories import ensure_local_directories
from job_application_copilot.services.prompt_content_migration import (
    PromptContentMigrationError,
    PromptContentMigrationService,
)

RemoteCleanerFactory = Callable[[], OpenAIRemoteCleanupOperations]


class ReferenceAssetResetError(RuntimeError):
    """Raised when a reset cannot safely remove the configured asset state."""


@dataclass(frozen=True, slots=True)
class ReferenceAssetResetResult:
    """Counts removed by one completed development reset."""

    reference_asset_count: int
    local_file_count: int
    openai_file_count: int
    vector_store_count: int


class ReferenceAssetResetService:
    """Remove all versioned Settings assets while preserving unrelated data."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        *,
        remote_cleaner_factory: RemoteCleanerFactory | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.remote_cleaner_factory = remote_cleaner_factory

    def reset(self) -> ReferenceAssetResetResult:
        """Delete remote resources, tracked local files, and reference-asset rows."""

        try:
            prompt_migration = PromptContentMigrationService(self.database, self.settings).migrate()
        except PromptContentMigrationError as error:
            raise ReferenceAssetResetError(
                "Cannot reset reference assets until legacy prompt text has been migrated safely."
            ) from error

        with self.database.session() as session:
            assets = ReferenceAssetRepository(session).list_all()

        local_paths = self._resolve_local_paths(assets)
        vector_store_ids = sorted(
            {
                asset.openai_vector_store_id
                for asset in assets
                if asset.openai_vector_store_id is not None
            }
        )
        openai_file_ids = sorted(
            {asset.openai_file_id for asset in assets if asset.openai_file_id is not None}
        )

        self._delete_remote_resources(vector_store_ids, openai_file_ids)

        deleted_file_count = prompt_migration.removed_legacy_file_count
        for path in local_paths:
            if path.is_file():
                path.unlink()
                deleted_file_count += 1

        with self.database.session() as session:
            deleted_asset_count = ReferenceAssetRepository(session).delete_all()

        return ReferenceAssetResetResult(
            reference_asset_count=deleted_asset_count,
            local_file_count=deleted_file_count,
            openai_file_count=len(openai_file_ids),
            vector_store_count=len(vector_store_ids),
        )

    def _resolve_local_paths(self, assets: list[ReferenceAsset]) -> tuple[Path, ...]:
        root = self.settings.reference_folder.resolve()
        paths: set[Path] = set()
        for asset in assets:
            if asset.asset_type is ReferenceAssetType.PROMPT:
                continue
            if asset.file_path is None:
                raise ReferenceAssetResetError(
                    f"File-backed reference asset '{asset.asset_key}' version {asset.version} "
                    "has no local path."
                )
            path = (self.settings.reference_folder / asset.file_path).resolve()
            if path == root or root not in path.parents:
                raise ReferenceAssetResetError(
                    f"Reference asset path is outside the configured reference folder: "
                    f"{asset.file_path}"
                )
            paths.add(path)
        return tuple(sorted(paths))

    def _delete_remote_resources(
        self,
        vector_store_ids: list[str],
        openai_file_ids: list[str],
    ) -> None:
        if not vector_store_ids and not openai_file_ids:
            return
        if self.remote_cleaner_factory is None:
            raise ReferenceAssetResetError(
                "OpenAI cleanup is required for stored remote reference assets."
            )

        cleaner = self.remote_cleaner_factory()
        try:
            for vector_store_id in vector_store_ids:
                cleaner.delete_vector_store(vector_store_id)
            for file_id in openai_file_ids:
                cleaner.delete_file(file_id)
        finally:
            cleaner.close()


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete all development reference-asset versions and files."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Confirm deletion of every stored reference-asset version.",
    )
    return parser.parse_args()


def main() -> None:
    """Reset the configured development reference assets after explicit confirmation."""

    arguments = _parse_arguments()
    if not arguments.force:
        raise SystemExit(
            "Reference-asset reset requires --force. "
            "Run '.\\dev.ps1 reset-reference-assets -Force'."
        )

    settings = load_settings()
    ensure_local_directories(settings)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        result = ReferenceAssetResetService(
            database,
            settings,
            remote_cleaner_factory=lambda: OpenAIClient.from_settings(settings),
        ).reset()
    finally:
        database.dispose()

    print(f"Reference assets deleted: {result.reference_asset_count}")
    print(f"Local reference files deleted: {result.local_file_count}")
    print(f"OpenAI files deleted: {result.openai_file_count}")
    print(f"OpenAI vector stores deleted: {result.vector_store_count}")
    print("Prompt definitions and jobs were preserved.")


if __name__ == "__main__":
    main()
