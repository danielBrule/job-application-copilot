"""Retain one row for every background-task execution attempt."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_create_background_task_attempts"
down_revision: str | None = "0011_create_background_task_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_task_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pipeline_step", sa.String(length=128), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("attempt_number > 0", name="ck_background_task_attempt_number_positive"),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED')",
            name="background_task_attempt_status",
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR status IN ('FAILED', 'INTERRUPTED')",
            name="ck_background_task_attempt_error_for_failure",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR status != 'RUNNING'",
            name="ck_background_task_attempt_running_not_completed",
        ),
        sa.UniqueConstraint("task_id", "attempt_number", name="uq_background_task_attempt_number"),
    )
    op.create_index(
        "ix_background_task_attempts_task_id",
        "background_task_attempts",
        ["task_id"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO background_task_attempts (
                task_id, attempt_number, status, pipeline_step,
                started_at, completed_at, error_message
            )
            SELECT
                id, retry_count + 1, status, pipeline_step,
                COALESCE(started_at, created_at), completed_at, error_message
            FROM background_tasks
            WHERE status != 'PENDING'
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_background_task_attempts_task_id",
        table_name="background_task_attempts",
    )
    op.drop_table("background_task_attempts")
