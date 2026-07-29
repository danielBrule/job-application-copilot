"""SQLAlchemy persistence models for durable background batches and tasks."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain import BackgroundOperation, BackgroundTaskStatus
from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import enum_values, utc_now


class BackgroundBatch(Base):
    """A user-requested group of tasks sharing one operation."""

    __tablename__ = "background_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    operation: Mapped[BackgroundOperation] = mapped_column(
        Enum(
            BackgroundOperation,
            name="background_operation",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    payload_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.current_timestamp()
    )


class BackgroundTask(Base):
    """One job-specific unit of durable background work."""

    __tablename__ = "background_tasks"
    __table_args__ = (
        CheckConstraint("retry_count >= 0", name="ck_background_tasks_retry_count_non_negative"),
        CheckConstraint(
            "error_message IS NULL OR status IN ('FAILED', 'INTERRUPTED')",
            name="ck_background_tasks_error_for_terminal_failure",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("background_batches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    operation: Mapped[BackgroundOperation] = mapped_column(
        Enum(
            BackgroundOperation,
            name="background_task_operation",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[BackgroundTaskStatus] = mapped_column(
        Enum(
            BackgroundTaskStatus,
            name="background_task_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=BackgroundTaskStatus.PENDING,
        server_default=BackgroundTaskStatus.PENDING.value,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    payload_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    pipeline_step: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
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
