"""Shared Streamlit state and presentation for reference-asset replacement."""

from typing import Protocol

from job_application_copilot.domain import ReferenceAssetProcessingStatus
from job_application_copilot.repositories.models import ReferenceAsset

REPLACEMENT_SUCCESS_KEY = "reference_asset_replacement_success"
REPLACEMENT_ERROR_KEY = "reference_asset_replacement_error"
REPLACEMENT_ERROR_MESSAGE = "The reference asset could not be stored. See the private UI log."


class UploadedDocx(Protocol):
    """Small boundary shared by Streamlit uploads and focused tests."""

    name: str

    def getvalue(self) -> bytes:
        """Return the complete uploaded content."""


def replacement_success_message(asset: ReferenceAsset) -> str:
    """Describe the active or retained state produced by a successful replacement."""

    if asset.processing_status is ReferenceAssetProcessingStatus.READY:
        return f"'{asset.asset_key}' version {asset.version} is active and READY."
    return (
        f"'{asset.asset_key}' version {asset.version} is stored as PENDING. "
        "Any existing active version remains in use."
    )
