"""SQLAlchemy persistence model for token-bearing LLM call telemetry."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain.background_task import BackgroundOperation
from job_application_copilot.domain.llm_call import LlmCallStatus, LlmFailureCategory
from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import enum_values, utc_now


class LlmCall(Base):
    """One completed provider invocation without prompt or response content."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint("call_sequence > 0", name="ck_llm_calls_call_sequence_positive"),
        CheckConstraint("retry_number >= 0", name="ck_llm_calls_retry_number_non_negative"),
        CheckConstraint("duration_seconds >= 0", name="ck_llm_calls_duration_non_negative"),
        CheckConstraint(
            "completed_at >= started_at",
            name="ck_llm_calls_timestamp_order",
        ),
        CheckConstraint(
            "task_attempt_id IS NULL OR task_id IS NOT NULL",
            name="ck_llm_calls_attempt_requires_task",
        ),
        CheckConstraint(
            "(status = 'SUCCEEDED' AND failure_category IS NULL) OR "
            "(status = 'FAILED' AND failure_category IS NOT NULL)",
            name="ck_llm_calls_failure_category_matches_status",
        ),
        CheckConstraint(
            "status != 'SUCCEEDED' OR "
            "(response_id IS NOT NULL AND input_tokens IS NOT NULL "
            "AND output_tokens IS NOT NULL AND total_tokens IS NOT NULL)",
            name="ck_llm_calls_success_has_core_usage",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_llm_calls_input_tokens_non_negative",
        ),
        CheckConstraint(
            "cached_input_tokens IS NULL OR cached_input_tokens >= 0",
            name="ck_llm_calls_cached_input_tokens_non_negative",
        ),
        CheckConstraint(
            "cache_write_tokens IS NULL OR cache_write_tokens >= 0",
            name="ck_llm_calls_cache_write_tokens_non_negative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_llm_calls_output_tokens_non_negative",
        ),
        CheckConstraint(
            "reasoning_tokens IS NULL OR reasoning_tokens >= 0",
            name="ck_llm_calls_reasoning_tokens_non_negative",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_llm_calls_total_tokens_non_negative",
        ),
        CheckConstraint(
            "cached_input_tokens IS NULL OR input_tokens IS NULL "
            "OR cached_input_tokens <= input_tokens",
            name="ck_llm_calls_cached_not_above_input",
        ),
        CheckConstraint(
            "(cache_identity_hash IS NULL AND cache_identity_version IS NULL) OR "
            "(cache_identity_hash IS NOT NULL AND length(cache_identity_hash) = 64 "
            "AND cache_identity_version > 0)",
            name="ck_llm_calls_cache_identity_complete",
        ),
        Index("ix_llm_calls_job_operation", "job_id", "operation"),
        Index("ix_llm_calls_task_id", "task_id"),
        Index("ix_llm_calls_task_attempt_id", "task_attempt_id"),
        Index("ix_llm_calls_cache_identity_hash", "cache_identity_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("background_tasks.id", ondelete="RESTRICT")
    )
    task_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("background_task_attempts.id", ondelete="RESTRICT")
    )
    operation: Mapped[BackgroundOperation] = mapped_column(
        Enum(
            BackgroundOperation,
            name="llm_call_operation",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    pipeline_step: Mapped[str] = mapped_column(String(128), nullable=False)
    call_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="OPENAI")
    requested_model: Mapped[str] = mapped_column(String(128), nullable=False)
    resolved_model: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[LlmCallStatus] = mapped_column(
        Enum(
            LlmCallStatus,
            name="llm_call_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    failure_category: Mapped[LlmFailureCategory | None] = mapped_column(
        Enum(
            LlmFailureCategory,
            name="llm_failure_category",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        )
    )
    retry_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_id: Mapped[str | None] = mapped_column(String(128))
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    incomplete_reason: Mapped[str | None] = mapped_column(String(128))
    service_tier: Mapped[str | None] = mapped_column(String(32))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    # NULL means unreported by the provider; zero means explicitly reported as zero.
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_identity_hash: Mapped[str | None] = mapped_column(String(64))
    cache_identity_version: Mapped[int | None] = mapped_column(Integer)
    cache_retention: Mapped[str | None] = mapped_column(String(32))
    version_metadata: Mapped[dict[str, str | int | bool | None]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
