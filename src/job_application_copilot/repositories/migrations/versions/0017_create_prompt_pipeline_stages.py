"""Create private durable outputs for resumable prompt-pipeline stages."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_create_prompt_pipeline_stages"
down_revision: str | None = "0016_add_job_cv_selection_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_pipeline_stages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage_position", sa.Integer(), nullable=False),
        sa.Column("pipeline_step", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_identity_hash", sa.String(length=64), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "stage_position > 0", name="ck_prompt_pipeline_stages_position_positive"
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED')", name="prompt_pipeline_stage_status"
        ),
        sa.CheckConstraint(
            "(status = 'SUCCEEDED' AND output_text IS NOT NULL) OR "
            "(status = 'FAILED' AND output_text IS NULL)",
            name="ck_prompt_pipeline_stages_output_matches_status",
        ),
        sa.UniqueConstraint(
            "task_id", "stage_position", name="uq_prompt_pipeline_stages_task_position"
        ),
    )
    op.create_index("ix_prompt_pipeline_stages_task_id", "prompt_pipeline_stages", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_prompt_pipeline_stages_task_id", table_name="prompt_pipeline_stages")
    op.drop_table("prompt_pipeline_stages")
