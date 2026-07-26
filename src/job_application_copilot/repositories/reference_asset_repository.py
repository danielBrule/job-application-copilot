"""Session-scoped persistence operations for reference assets."""

from sqlalchemy import func, select
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

    def find_by_hash(self, asset_key: str, file_hash: str) -> ReferenceAsset | None:
        """Return a matching version for the same logical asset, if one exists."""

        return self.session.scalar(
            select(ReferenceAsset).where(
                ReferenceAsset.asset_key == asset_key,
                ReferenceAsset.file_hash == file_hash,
            )
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
