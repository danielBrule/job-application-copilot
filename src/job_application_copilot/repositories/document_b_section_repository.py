"""Persistence operations for extracted Document B sections."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from job_application_copilot.errors import ApplicationNotFoundError
from job_application_copilot.repositories.models import DocumentBSection


class DocumentBSectionNotFoundError(ApplicationNotFoundError):
    """Raised when a requested section ID is absent from a Document B version."""

    def __init__(self, version: int, section_id: str) -> None:
        super().__init__(f"Document B version {version} has no extracted section '{section_id}'.")


class DocumentBSectionRepository:
    """Read and replace sections within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace(
        self,
        reference_asset_id: int,
        sections: list[DocumentBSection],
    ) -> None:
        """Atomically replace all extracted sections for one reference version."""

        self.session.execute(
            delete(DocumentBSection).where(
                DocumentBSection.reference_asset_id == reference_asset_id
            )
        )
        self.session.add_all(sections)
        self.session.flush()

    def list_for_asset(self, reference_asset_id: int) -> list[DocumentBSection]:
        """Return one version's sections in original document order."""

        return list(
            self.session.scalars(
                select(DocumentBSection)
                .where(DocumentBSection.reference_asset_id == reference_asset_id)
                .order_by(DocumentBSection.sequence)
            )
        )

    def get_by_section_id(
        self,
        reference_asset_id: int,
        section_id: str,
    ) -> DocumentBSection | None:
        """Return a stable section ID for one exact Document B version."""

        return self.session.scalar(
            select(DocumentBSection).where(
                DocumentBSection.reference_asset_id == reference_asset_id,
                DocumentBSection.section_id == section_id,
            )
        )
