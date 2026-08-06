"""Create private structured records for stage-two CV drafts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_create_cv_generation_drafts"
down_revision: str | None = "0018_create_cv_generation_briefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cv_generation_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_a_version", sa.Integer(), nullable=False),
        sa.Column("document_b_version", sa.Integer(), nullable=False),
        sa.Column("routing_set_id", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.UniqueConstraint("task_id", name="uq_cv_generation_drafts_task"),
    )
    op.create_index("ix_cv_generation_drafts_task_id", "cv_generation_drafts", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_cv_generation_drafts_task_id", table_name="cv_generation_drafts")
    op.drop_table("cv_generation_drafts")
