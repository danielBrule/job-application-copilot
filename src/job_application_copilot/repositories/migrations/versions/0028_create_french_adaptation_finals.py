"""Create private structured records for reviewed French CVs.

Revision ID: 0028_create_french_adaptation_finals
Revises: 0027_create_french_adaptation_drafts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_create_french_adaptation_finals"
down_revision: str | None = "0027_create_french_adaptation_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "french_adaptation_finals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_locale", sa.String(length=16), nullable=False),
        sa.Column("document_a_version", sa.Integer(), nullable=False),
        sa.Column("document_b_version", sa.Integer(), nullable=False),
        sa.Column("english_final_prompt_version", sa.Integer(), nullable=False),
        sa.Column("french_adaptation_prompt_version", sa.Integer(), nullable=False),
        sa.Column("french_review_prompt_version", sa.Integer(), nullable=False),
        sa.Column("english_template_version", sa.Integer(), nullable=False),
        sa.Column("french_template_version", sa.Integer(), nullable=False),
        sa.Column("french_reference_versions", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.UniqueConstraint("task_id", name="uq_french_adaptation_finals_task"),
    )
    op.create_index("ix_french_adaptation_finals_task_id", "french_adaptation_finals", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_french_adaptation_finals_task_id", table_name="french_adaptation_finals")
    op.drop_table("french_adaptation_finals")
