"""Add processed vector-store usage to reference assets."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_reference_asset_vector_store_usage"
down_revision: str | None = "0005_add_reference_asset_processing_error"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store the processed bytes reported for one asset's vector store."""

    op.add_column(
        "reference_assets",
        sa.Column(
            "openai_vector_store_usage_bytes",
            sa.Integer(),
            sa.CheckConstraint(
                "openai_vector_store_usage_bytes >= 0",
                name="ck_reference_assets_vector_store_usage_bytes_non_negative",
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove persisted vector-store usage."""

    op.drop_column("reference_assets", "openai_vector_store_usage_bytes")
