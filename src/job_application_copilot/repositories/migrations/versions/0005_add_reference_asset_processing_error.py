"""Add the latest reference-asset processing error."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_reference_asset_processing_error"
down_revision: str | None = "0004_create_prompt_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store one actionable, sanitised processing failure per asset version."""

    op.add_column(
        "reference_assets",
        sa.Column("processing_error", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    """Remove persisted processing-error details."""

    op.drop_column("reference_assets", "processing_error")
