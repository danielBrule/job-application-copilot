"""Add durable pre-generation CV selection state to jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_add_job_cv_selection_status"
down_revision: str | None = "0015_optional_secondary_role_family"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Default existing jobs to not selected for CV generation."""

    op.add_column(
        "jobs",
        sa.Column(
            "cv_selection_status",
            sa.Enum(
                "NOT_SELECTED",
                "SELECTED",
                name="job_cv_selection_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'NOT_SELECTED'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove the pre-generation CV selection state."""

    op.drop_column("jobs", "cv_selection_status")
