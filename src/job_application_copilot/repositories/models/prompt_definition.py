"""SQLAlchemy persistence model for data-driven prompt definitions."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import utc_now


class PromptDefinition(Base):
    """Stable pipeline metadata shared by every version of one prompt."""

    __tablename__ = "prompt_definitions"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_group",
            "position",
            name="uq_prompt_definitions_group_position",
        ),
        CheckConstraint(
            "length(trim(asset_key)) > 0",
            name="ck_prompt_definitions_key_not_blank",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_prompt_definitions_name_not_blank",
        ),
        CheckConstraint(
            "length(trim(pipeline_group)) > 0",
            name="ck_prompt_definitions_group_not_blank",
        ),
        CheckConstraint(
            "language_code IS NULL OR length(trim(language_code)) > 0",
            name="ck_prompt_definitions_language_not_blank",
        ),
        CheckConstraint(
            "language_code IS NULL OR language_code = lower(language_code)",
            name="ck_prompt_definitions_language_lowercase",
        ),
        CheckConstraint(
            "position > 0",
            name="ck_prompt_definitions_position_positive",
        ),
    )

    asset_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pipeline_group: Mapped[str] = mapped_column(String(255), nullable=False)
    language_code: Mapped[str | None] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    created_at: Mapped[datetime] = mapped_column(
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
