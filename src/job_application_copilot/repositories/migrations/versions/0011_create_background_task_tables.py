"""Create durable background batches and job-specific task records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_create_background_task_tables"
down_revision: str | None = "0010_create_document_b_retrieval_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("payload_metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.CheckConstraint(
            "operation IN ('ASSESSMENT', 'CV_GENERATION')", name="background_operation"
        ),
    )
    op.create_table(
        "background_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("background_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload_metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("pipeline_step", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.CheckConstraint(
            "operation IN ('ASSESSMENT', 'CV_GENERATION')", name="background_task_operation"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED')",
            name="background_task_status",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_background_tasks_retry_count_non_negative"),
        sa.CheckConstraint(
            "error_message IS NULL OR status IN ('FAILED', 'INTERRUPTED')",
            name="ck_background_tasks_error_for_terminal_failure",
        ),
    )
    op.create_index("ix_background_tasks_batch_id", "background_tasks", ["batch_id"])
    op.create_index("ix_background_tasks_job_id", "background_tasks", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_background_tasks_job_id", table_name="background_tasks")
    op.drop_index("ix_background_tasks_batch_id", table_name="background_tasks")
    op.drop_table("background_tasks")
    op.drop_table("background_batches")
