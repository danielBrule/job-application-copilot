"""SQLAlchemy model for one job's current CV file and review state."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain import CvSource, CvStatus, Language
from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import enum_values, utc_now


class Cv(Base):
    """The sole active CV record for one job, without Word-version history."""

    __tablename__ = "cvs"
    __table_args__ = (
        CheckConstraint(
            "length(trim(file_name)) > 0 OR file_name IS NULL", name="ck_cvs_name_not_blank"
        ),
        CheckConstraint(
            "length(trim(file_path)) > 0 OR file_path IS NULL", name="ck_cvs_path_not_blank"
        ),
        CheckConstraint(
            "status NOT IN ('READY_FOR_REVIEW', 'APPROVED') "
            "OR (file_name IS NOT NULL AND file_path IS NOT NULL)",
            name="ck_cvs_ready_requires_file",
        ),
        CheckConstraint(
            "(status = 'APPROVED' AND approved_at IS NOT NULL) "
            "OR (status != 'APPROVED' AND approved_at IS NULL)",
            name="ck_cvs_approval_matches_status",
        ),
        CheckConstraint(
            "(status = 'FAILED' AND error_message IS NOT NULL AND length(trim(error_message)) > 0) "
            "OR (status != 'FAILED' AND error_message IS NULL)",
            name="ck_cvs_error_matches_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    source: Mapped[CvSource] = mapped_column(
        Enum(
            CvSource,
            name="cv_source",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[CvStatus] = mapped_column(
        Enum(
            CvStatus,
            name="cv_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    language: Mapped[Language] = mapped_column(
        Enum(
            Language,
            name="cv_language",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(2048))
    selected_cv_lane: Mapped[str | None] = mapped_column(String(255))
    document_a_version: Mapped[int | None] = mapped_column(Integer)
    document_b_version: Mapped[int | None] = mapped_column(Integer)
    template_version: Mapped[int | None] = mapped_column(Integer)
    generation_prompt_versions: Mapped[dict[str, int] | None] = mapped_column(JSON)
    french_prompt_versions: Mapped[dict[str, int] | None] = mapped_column(JSON)
    review_notes: Mapped[str | None] = mapped_column(Text)
    generated_or_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )
