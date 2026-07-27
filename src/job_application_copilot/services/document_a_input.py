"""Prepare the complete active Document A file reference for assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, TypedDict

from job_application_copilot.domain import (
    DOCUMENT_A_KEY,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)


class OpenAIInputFile(TypedDict):
    """Responses API input-file reference."""

    type: Literal["input_file"]
    file_id: str


class DocumentAInputUnavailableError(RuntimeError):
    """Raised when no complete active Document A file can be referenced."""


@dataclass(frozen=True, slots=True)
class DocumentAInput:
    """Immutable active Document A reference and traceability metadata."""

    reference_asset_id: int
    version: int
    file_hash: str
    stored_filename: str
    openai_file_id: str
    uploaded_at: datetime

    def to_openai_input_file(self) -> OpenAIInputFile:
        """Return the complete uploaded DOCX as a Responses API content item."""

        return {
            "type": "input_file",
            "file_id": self.openai_file_id,
        }


class DocumentAInputService:
    """Resolve only the active canonical Document A uploaded to OpenAI."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def prepare(self) -> DocumentAInput:
        """Prepare the exact active Document A file and its persisted version."""

        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).get_active(DOCUMENT_A_KEY)
            if asset is None:
                raise DocumentAInputUnavailableError(
                    "No active Document A is available. In Settings, store Document A "
                    "if needed, then choose 'Restore and activate with OpenAI'."
                )
            openai_file_id = self._require_active_asset(asset)
            return DocumentAInput(
                reference_asset_id=asset.id,
                version=asset.version,
                file_hash=asset.file_hash,
                stored_filename=PurePosixPath(asset.file_path).name,
                openai_file_id=openai_file_id,
                uploaded_at=asset.uploaded_at,
            )

    @staticmethod
    def _require_active_asset(asset: ReferenceAsset) -> str:
        if asset.asset_key != DOCUMENT_A_KEY or asset.asset_type is not ReferenceAssetType.DOCUMENT:
            raise DocumentAInputUnavailableError(
                "The active 'document-a' reference is not the canonical Document A."
            )
        if asset.processing_status is not ReferenceAssetProcessingStatus.READY:
            raise DocumentAInputUnavailableError(
                "The active Document A is not READY for assessment."
            )
        if asset.openai_file_id is None or not asset.openai_file_id.strip():
            raise DocumentAInputUnavailableError(
                "The active Document A has no OpenAI file reference. "
                "Activate it with OpenAI again in Settings."
            )
        return asset.openai_file_id
