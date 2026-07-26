"""Session-scoped persistence operations for reference assets."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_application_copilot.repositories.models import ReferenceAsset


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
