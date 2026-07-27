"""SQLAlchemy persistence model for locally extracted Document B sections."""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.repositories.base import Base


class DocumentBSection(Base):
    """One ordered heading section extracted from one Document B version."""

    __tablename__ = "document_b_sections"
    __table_args__ = (
        UniqueConstraint(
            "reference_asset_id",
            "section_id",
            name="uq_document_b_sections_asset_section_id",
        ),
        UniqueConstraint(
            "reference_asset_id",
            "sequence",
            name="uq_document_b_sections_asset_sequence",
        ),
        CheckConstraint(
            "length(trim(section_id)) > 0",
            name="ck_document_b_sections_id_not_blank",
        ),
        CheckConstraint(
            "length(trim(heading_title)) > 0",
            name="ck_document_b_sections_title_not_blank",
        ),
        CheckConstraint(
            "heading_level >= 0",
            name="ck_document_b_sections_level_non_negative",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_document_b_sections_sequence_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_asset_id: Mapped[int] = mapped_column(
        ForeignKey("reference_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[str] = mapped_column(String(255), nullable=False)
    heading_number: Mapped[str | None] = mapped_column(String(64))
    heading_title: Mapped[str] = mapped_column(String(512), nullable=False)
    heading_level: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    section_text: Mapped[str] = mapped_column(Text, nullable=False)
