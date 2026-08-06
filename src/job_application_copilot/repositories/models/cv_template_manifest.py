"""Private mapping record for one immutable English DOCX template version."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain import CvTemplateManifestStatus
from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import enum_values, utc_now


class CvTemplateManifestRecord(Base):
    __tablename__ = "cv_template_manifests"
    __table_args__ = (UniqueConstraint("template_asset_id", name="uq_cv_template_manifests_asset"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    template_asset_id: Mapped[int] = mapped_column(
        ForeignKey("reference_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[CvTemplateManifestStatus] = mapped_column(
        Enum(
            CvTemplateManifestStatus,
            name="cv_template_manifest_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    placeholders: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    slots: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
