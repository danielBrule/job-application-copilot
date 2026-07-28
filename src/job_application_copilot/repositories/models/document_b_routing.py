"""Persistence models for immutable version-bound Document B routing sets."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain import CvLane, DocumentBRoutingSetStatus
from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import enum_values, utc_now


class DocumentBRoutingSet(Base):
    """One immutable generated manifest for one exact Document B version."""

    __tablename__ = "document_b_routing_sets"
    __table_args__ = (
        CheckConstraint(
            "length(trim(routing_config_version)) > 0",
            name="ck_document_b_routing_sets_config_version_not_blank",
        ),
        Index(
            "uq_document_b_routing_sets_current_asset",
            "reference_asset_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_asset_id: Mapped[int] = mapped_column(
        ForeignKey("reference_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    routing_config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    routing_config_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    document_b_file_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    extracted_section_catalog_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    status: Mapped[DocumentBRoutingSetStatus] = mapped_column(
        Enum(
            DocumentBRoutingSetStatus,
            name="document_b_routing_set_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
    validation_error: Mapped[str | None] = mapped_column(Text)


class DocumentBLaneRoute(Base):
    """One resolved lane packet stored as validated immutable JSON."""

    __tablename__ = "document_b_lane_routes"
    __table_args__ = (
        UniqueConstraint("routing_set_id", "lane_id", name="uq_document_b_lane_routes_set_lane"),
        CheckConstraint(
            "length(trim(ordered_route_json)) > 0",
            name="ck_document_b_lane_routes_packet_not_blank",
        ),
        CheckConstraint(
            "length(trim(secondary_lane_constraints_json)) > 0",
            name="ck_document_b_lane_routes_constraints_not_blank",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    routing_set_id: Mapped[int] = mapped_column(
        ForeignKey("document_b_routing_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lane_id: Mapped[CvLane] = mapped_column(
        Enum(
            CvLane,
            name="cv_lane",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    ordered_route_json: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_lane_constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
