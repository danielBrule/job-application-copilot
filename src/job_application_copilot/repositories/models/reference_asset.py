"""SQLAlchemy persistence model for versioned reference assets."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import enum_values, utc_now


class ReferenceAsset(Base):
    """Metadata for one immutable version of a private reference input."""

    __tablename__ = "reference_assets"
    __table_args__ = (
        UniqueConstraint(
            "asset_key",
            "version",
            name="uq_reference_assets_key_version",
        ),
        CheckConstraint(
            "length(trim(asset_key)) > 0",
            name="ck_reference_assets_key_not_blank",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_reference_assets_name_not_blank",
        ),
        CheckConstraint(
            "language_code IS NULL OR length(trim(language_code)) > 0",
            name="ck_reference_assets_language_not_blank",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_reference_assets_version_positive",
        ),
        CheckConstraint(
            "length(trim(file_path)) > 0",
            name="ck_reference_assets_path_not_blank",
        ),
        CheckConstraint(
            "length(trim(file_hash)) > 0",
            name="ck_reference_assets_hash_not_blank",
        ),
        CheckConstraint(
            "openai_file_id IS NULL OR length(trim(openai_file_id)) > 0",
            name="ck_reference_assets_openai_file_id_not_blank",
        ),
        CheckConstraint(
            "openai_vector_store_id IS NULL OR length(trim(openai_vector_store_id)) > 0",
            name="ck_reference_assets_vector_store_id_not_blank",
        ),
        CheckConstraint(
            "is_active = 0 OR processing_status = 'READY'",
            name="ck_reference_assets_active_ready",
        ),
        Index(
            "uq_reference_assets_active_key",
            "asset_key",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_key: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[ReferenceAssetType] = mapped_column(
        Enum(
            ReferenceAssetType,
            name="reference_asset_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    language_code: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    processing_status: Mapped[ReferenceAssetProcessingStatus] = mapped_column(
        Enum(
            ReferenceAssetProcessingStatus,
            name="reference_asset_processing_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ReferenceAssetProcessingStatus.PENDING,
        server_default=ReferenceAssetProcessingStatus.PENDING.value,
    )
    openai_file_id: Mapped[str | None] = mapped_column(String(255))
    openai_vector_store_id: Mapped[str | None] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )
