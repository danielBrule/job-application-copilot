"""Create privacy-safe usage records for token-bearing LLM calls."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_create_llm_calls"
down_revision: str | None = "0012_create_background_task_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("background_tasks.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "task_attempt_id",
            sa.Integer(),
            sa.ForeignKey("background_task_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("pipeline_step", sa.String(length=128), nullable=False),
        sa.Column("call_sequence", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("requested_model", sa.String(length=128), nullable=False),
        sa.Column("resolved_model", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_category", sa.String(length=32), nullable=True),
        sa.Column("retry_number", sa.Integer(), nullable=False),
        sa.Column("response_id", sa.String(length=128), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("incomplete_reason", sa.String(length=128), nullable=True),
        sa.Column("service_tier", sa.String(length=32), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_identity_hash", sa.String(length=64), nullable=True),
        sa.Column("cache_identity_version", sa.Integer(), nullable=True),
        sa.Column("cache_retention", sa.String(length=32), nullable=True),
        sa.Column("version_metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.CheckConstraint(
            "operation IN ('ASSESSMENT', 'CV_GENERATION')", name="llm_call_operation"
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED')",
            name="llm_call_status",
        ),
        sa.CheckConstraint(
            "failure_category IS NULL OR failure_category IN "
            "('TIMEOUT', 'RATE_LIMIT', 'NETWORK', 'PROVIDER', 'INCOMPLETE_RESPONSE', "
            "'SCHEMA_VALIDATION', 'INTERRUPTED', 'UNKNOWN')",
            name="llm_failure_category",
        ),
        sa.CheckConstraint("call_sequence > 0", name="ck_llm_calls_call_sequence_positive"),
        sa.CheckConstraint("retry_number >= 0", name="ck_llm_calls_retry_number_non_negative"),
        sa.CheckConstraint("duration_seconds >= 0", name="ck_llm_calls_duration_non_negative"),
        sa.CheckConstraint("completed_at >= started_at", name="ck_llm_calls_timestamp_order"),
        sa.CheckConstraint(
            "task_attempt_id IS NULL OR task_id IS NOT NULL",
            name="ck_llm_calls_attempt_requires_task",
        ),
        sa.CheckConstraint(
            "(status = 'SUCCEEDED' AND failure_category IS NULL) OR "
            "(status = 'FAILED' AND failure_category IS NOT NULL)",
            name="ck_llm_calls_failure_category_matches_status",
        ),
        sa.CheckConstraint(
            "status != 'SUCCEEDED' OR "
            "(response_id IS NOT NULL AND input_tokens IS NOT NULL "
            "AND output_tokens IS NOT NULL AND total_tokens IS NOT NULL)",
            name="ck_llm_calls_success_has_core_usage",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_llm_calls_input_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "cached_input_tokens IS NULL OR cached_input_tokens >= 0",
            name="ck_llm_calls_cached_input_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "cache_write_tokens IS NULL OR cache_write_tokens >= 0",
            name="ck_llm_calls_cache_write_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_llm_calls_output_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "reasoning_tokens IS NULL OR reasoning_tokens >= 0",
            name="ck_llm_calls_reasoning_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_llm_calls_total_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "cached_input_tokens IS NULL OR input_tokens IS NULL "
            "OR cached_input_tokens <= input_tokens",
            name="ck_llm_calls_cached_not_above_input",
        ),
        sa.CheckConstraint(
            "(cache_identity_hash IS NULL AND cache_identity_version IS NULL) OR "
            "(cache_identity_hash IS NOT NULL AND length(cache_identity_hash) = 64 "
            "AND cache_identity_version > 0)",
            name="ck_llm_calls_cache_identity_complete",
        ),
    )
    op.create_index("ix_llm_calls_job_operation", "llm_calls", ["job_id", "operation"])
    op.create_index("ix_llm_calls_task_id", "llm_calls", ["task_id"])
    op.create_index("ix_llm_calls_task_attempt_id", "llm_calls", ["task_attempt_id"])
    op.create_index("ix_llm_calls_cache_identity_hash", "llm_calls", ["cache_identity_hash"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_cache_identity_hash", table_name="llm_calls")
    op.drop_index("ix_llm_calls_task_attempt_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_task_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_job_operation", table_name="llm_calls")
    op.drop_table("llm_calls")
