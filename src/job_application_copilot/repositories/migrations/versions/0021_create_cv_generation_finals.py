"""Create private structured records for stage-three final CVs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_create_cv_generation_finals"
down_revision: str | None = "0020_create_cv_template_manifests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cv_generation_finals",
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
        sa.UniqueConstraint("task_id", name="uq_cv_generation_finals_task"),
    )
    op.create_index("ix_cv_generation_finals_task_id", "cv_generation_finals", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_cv_generation_finals_task_id", table_name="cv_generation_finals")
    op.drop_table("cv_generation_finals")
