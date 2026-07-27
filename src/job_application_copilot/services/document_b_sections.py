"""Extract and persist deterministic sections for retained Document B versions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.documents.document_b_extraction import (
    DocumentBExtractionError,
    ExtractedDocumentBSection,
    extract_document_b_sections,
)
from job_application_copilot.domain import DOCUMENT_B_KEY, ReferenceAssetType
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.document_b_section_repository import (
    DocumentBSectionNotFoundError,
    DocumentBSectionRepository,
)
from job_application_copilot.repositories.models import DocumentBSection
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)


class DocumentBSectionError(RuntimeError):
    """Raised when one Document B version cannot provide reliable local sections."""


@dataclass(frozen=True, slots=True)
class DocumentBSectionRecord:
    """Presentation-neutral persisted section tied to one Document B version."""

    document_b_version: int
    section_id: str
    heading_number: str | None
    heading_title: str
    heading_level: int
    sequence: int
    section_text: str


class DocumentBSectionService:
    """Coordinate local integrity checks, extraction, and versioned persistence."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings

    def extract_and_store(self, version: int) -> tuple[DocumentBSectionRecord, ...]:
        """Idempotently replace one version's sections from its retained DOCX."""

        reference_asset_id, file_path, expected_hash = self._source(version)
        content = self._read_verified(version, file_path, expected_hash)
        try:
            extracted = extract_document_b_sections(content)
        except DocumentBExtractionError as error:
            raise DocumentBSectionError(str(error)) from error

        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(DOCUMENT_B_KEY, version)
            if asset.id != reference_asset_id:
                raise DocumentBSectionError(
                    f"Document B version {version} changed during section extraction."
                )
            models = [
                DocumentBSection(
                    reference_asset_id=reference_asset_id,
                    section_id=section.section_id,
                    heading_number=section.heading_number,
                    heading_title=section.heading_title,
                    heading_level=section.heading_level,
                    sequence=section.sequence,
                    section_text=section.section_text,
                )
                for section in extracted
            ]
            DocumentBSectionRepository(session).replace(reference_asset_id, models)
        return tuple(_record(version, section) for section in extracted)

    def list_sections(self, version: int) -> tuple[DocumentBSectionRecord, ...]:
        """Return sections in source order, extracting a legacy version on first use."""

        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(DOCUMENT_B_KEY, version)
            self._validate_document_b(asset.asset_key, asset.asset_type)
            sections = DocumentBSectionRepository(session).list_for_asset(asset.id)
            records = tuple(_record_from_model(version, section) for section in sections)
        if records:
            return records
        return self.extract_and_store(version)

    def require_section(self, version: int, section_id: str) -> DocumentBSectionRecord:
        """Retrieve one stable section ID from an exact Document B version."""

        section = self._find_section(section_id, self.list_sections(version))
        if section is None:
            raise DocumentBSectionNotFoundError(version, section_id)
        return section

    def list_section_tree(
        self,
        version: int,
        section_id: str,
    ) -> tuple[DocumentBSectionRecord, ...]:
        """Return one heading and its ordered descendants without duplicating stored text."""

        sections = self.list_sections(version)
        root = self._find_section(section_id, sections)
        if root is None:
            raise DocumentBSectionNotFoundError(version, section_id)

        tree: list[DocumentBSectionRecord] = []
        for section in sections[sections.index(root) :]:
            if tree and section.heading_level <= root.heading_level:
                break
            tree.append(section)
        return tuple(tree)

    @staticmethod
    def _find_section(
        section_id: str,
        sections: tuple[DocumentBSectionRecord, ...],
    ) -> DocumentBSectionRecord | None:
        return next(
            (candidate for candidate in sections if candidate.section_id == section_id),
            None,
        )

    def _source(self, version: int) -> tuple[int, str, str]:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(DOCUMENT_B_KEY, version)
            self._validate_document_b(asset.asset_key, asset.asset_type)
            return asset.id, asset.file_path, asset.file_hash

    def _read_verified(self, version: int, file_path: str, expected_hash: str) -> bytes:
        path = self._resolve_stored_path(file_path)
        try:
            content = path.read_bytes()
        except OSError as error:
            raise DocumentBSectionError(
                f"Stored Document B version {version} cannot be read."
            ) from error
        actual_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if actual_hash != expected_hash:
            raise DocumentBSectionError(
                f"Stored Document B version {version} no longer matches its recorded hash."
            )
        return content

    def _resolve_stored_path(self, file_path: str) -> Path:
        reference_root = self.settings.reference_folder.resolve()
        stored_path = (reference_root / Path(file_path)).resolve()
        try:
            stored_path.relative_to(reference_root)
        except ValueError as error:
            raise DocumentBSectionError(
                "The stored Document B path is outside the configured reference folder."
            ) from error
        if not stored_path.is_file():
            raise DocumentBSectionError("The stored Document B file no longer exists.")
        return stored_path

    @staticmethod
    def _validate_document_b(asset_key: str, asset_type: ReferenceAssetType) -> None:
        if asset_key != DOCUMENT_B_KEY or asset_type is not ReferenceAssetType.DOCUMENT:
            raise DocumentBSectionError(
                "Only canonical Document B versions may have extracted sections."
            )


def _record(
    version: int,
    section: ExtractedDocumentBSection,
) -> DocumentBSectionRecord:
    return DocumentBSectionRecord(
        document_b_version=version,
        section_id=section.section_id,
        heading_number=section.heading_number,
        heading_title=section.heading_title,
        heading_level=section.heading_level,
        sequence=section.sequence,
        section_text=section.section_text,
    )


def _record_from_model(
    version: int,
    section: DocumentBSection,
) -> DocumentBSectionRecord:
    return DocumentBSectionRecord(
        document_b_version=version,
        section_id=section.section_id,
        heading_number=section.heading_number,
        heading_title=section.heading_title,
        heading_level=section.heading_level,
        sequence=section.sequence,
        section_text=section.section_text,
    )
