"""Session-scoped persistence operations for reference assets."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories.models import ReferenceAsset


class ReferenceAssetVersionNotFoundError(LookupError):
    """Raised when a required immutable asset version does not exist."""

    def __init__(self, asset_key: str, version: int) -> None:
        self.asset_key = asset_key
        self.version = version
        super().__init__(f"Reference asset '{asset_key}' version {version} does not exist.")


class ReferenceAssetRepository:
    """Read and write reference assets within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, asset: ReferenceAsset) -> ReferenceAsset:
        """Persist reference-asset metadata and populate generated values."""

        self.session.add(asset)
        self.session.flush()
        return asset

    def list_all(self) -> list[ReferenceAsset]:
        """Return every retained reference-asset version in stable order."""

        return list(
            self.session.scalars(
                select(ReferenceAsset).order_by(
                    ReferenceAsset.asset_key,
                    ReferenceAsset.version,
                )
            )
        )

    def delete_all(self) -> int:
        """Delete every reference-asset version and return the affected row count."""

        result = self.session.execute(delete(ReferenceAsset))
        return result.rowcount

    def find_by_hash(self, asset_key: str, file_hash: str) -> ReferenceAsset | None:
        """Return a matching version for the same logical asset, if one exists."""

        return self.session.scalar(
            select(ReferenceAsset).where(
                ReferenceAsset.asset_key == asset_key,
                ReferenceAsset.file_hash == file_hash,
            )
        )

    def find_by_hash_for_type(
        self,
        asset_type: ReferenceAssetType,
        file_hash: str,
    ) -> ReferenceAsset | None:
        """Return matching content anywhere in one reference-asset category."""

        return self.session.scalar(
            select(ReferenceAsset)
            .where(
                ReferenceAsset.asset_type == asset_type,
                ReferenceAsset.file_hash == file_hash,
            )
            .order_by(ReferenceAsset.uploaded_at.desc(), ReferenceAsset.id.desc())
        )

    def next_version(self, asset_key: str) -> int:
        """Return the next positive immutable version for a logical asset."""

        current_version = self.session.scalar(
            select(func.max(ReferenceAsset.version)).where(ReferenceAsset.asset_key == asset_key)
        )
        return (current_version or 0) + 1

    def get_active(self, asset_key: str) -> ReferenceAsset | None:
        """Return the active version of one logical asset, if present."""

        return self.session.scalar(
            select(ReferenceAsset).where(
                ReferenceAsset.asset_key == asset_key,
                ReferenceAsset.is_active.is_(True),
            )
        )

    def require_version(self, asset_key: str, version: int) -> ReferenceAsset:
        """Return a specific version or raise an actionable lookup error."""

        asset = self.session.scalar(
            select(ReferenceAsset).where(
                ReferenceAsset.asset_key == asset_key,
                ReferenceAsset.version == version,
            )
        )
        if asset is None:
            raise ReferenceAssetVersionNotFoundError(asset_key, version)
        return asset

    def list_versions(self, asset_key: str) -> list[ReferenceAsset]:
        """Return all versions of a logical asset, newest first."""

        return list(
            self.session.scalars(
                select(ReferenceAsset)
                .where(ReferenceAsset.asset_key == asset_key)
                .order_by(ReferenceAsset.version.desc())
            )
        )

    def list_by_type(
        self,
        asset_type: ReferenceAssetType,
        *,
        language_code: str | None = None,
    ) -> list[ReferenceAsset]:
        """Return category versions in stable logical-key and newest-first order."""

        statement = select(ReferenceAsset).where(ReferenceAsset.asset_type == asset_type)
        if language_code is not None:
            statement = statement.where(ReferenceAsset.language_code == language_code)
        statement = statement.order_by(
            ReferenceAsset.asset_key,
            ReferenceAsset.version.desc(),
        )
        return list(self.session.scalars(statement))

    def list_active_ready_prompts(self) -> list[ReferenceAsset]:
        """Return active prompt versions that are ready for use."""

        return list(
            self.session.scalars(
                select(ReferenceAsset).where(
                    ReferenceAsset.asset_type == ReferenceAssetType.PROMPT,
                    ReferenceAsset.processing_status == ReferenceAssetProcessingStatus.READY,
                    ReferenceAsset.is_active.is_(True),
                )
            )
        )
