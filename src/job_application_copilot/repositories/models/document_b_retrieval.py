"""Persistence models for section-scoped Document B retrieval."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.repositories.base import Base


class DocumentBVectorRecord(Base):
    """One remotely indexed, locally verified Document B section source."""

    __tablename__ = "document_b_vector_records"
    __table_args__ = (
        UniqueConstraint(
            "reference_asset_id", "section_id", name="uq_document_b_vector_record_section"
        ),
        UniqueConstraint("openai_file_id", name="uq_document_b_vector_record_openai_file"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_asset_id: Mapped[int] = mapped_column(
        ForeignKey("reference_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    openai_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    vector_store_id: Mapped[str] = mapped_column(String(255), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class DocumentBRetrievalTrace(Base):
    """Private local record of one reproducible supplementary retrieval."""

    __tablename__ = "document_b_retrieval_traces"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_asset_id: Mapped[int] = mapped_column(
        ForeignKey("reference_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    routing_set_id: Mapped[int] = mapped_column(
        ForeignKey("document_b_routing_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    routing_config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class DocumentBRetrievalTraceResult(Base):
    """One returned passage, retained only in private local trace data."""

    __tablename__ = "document_b_retrieval_trace_results"
    __table_args__ = (
        UniqueConstraint("trace_id", "passage_id", name="uq_document_b_trace_passage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[int] = mapped_column(
        ForeignKey("document_b_retrieval_traces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vector_record_id: Mapped[int] = mapped_column(
        ForeignKey("document_b_vector_records.id", ondelete="RESTRICT"), nullable=False
    )
    passage_id: Mapped[str] = mapped_column(String(71), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    passage_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
