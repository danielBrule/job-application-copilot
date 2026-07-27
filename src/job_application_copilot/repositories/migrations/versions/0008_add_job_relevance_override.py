"""Add the optional human relevance override to jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_job_relevance_override"
down_revision: str | None = "0007_create_document_b_sections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist a constrained, nullable user relevance override."""

    op.add_column(
        "jobs",
        sa.Column(
            "relevance_override",
            sa.String(length=6),
            sa.CheckConstraint(
                "relevance_override IN ('HIGH', 'MEDIUM', 'LOW')",
                name="job_relevance_override",
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the user relevance override."""

    op.drop_column("jobs", "relevance_override")
