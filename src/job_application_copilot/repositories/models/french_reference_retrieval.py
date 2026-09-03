"""Persistence models for searchable French style-reference sources."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.repositories.base import Base


class FrenchReferenceVectorStore(Base):
    """The single shared vector store containing active French-reference sources."""

    __tablename__ = "french_reference_vector_stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vector_store_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class FrenchReferenceVectorSource(Base):
    """One locally verified French CV source indexed in the shared store."""

    __tablename__ = "french_reference_vector_sources"
    __table_args__ = (
        UniqueConstraint("reference_asset_id", name="uq_french_reference_vector_source_asset"),
        UniqueConstraint("openai_file_id", name="uq_french_reference_vector_source_openai_file"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_asset_id: Mapped[int] = mapped_column(
        ForeignKey("reference_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vector_store_id: Mapped[str] = mapped_column(String(255), nullable=False)
    openai_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
