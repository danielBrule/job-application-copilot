"""Create private placeholder manifests for English CV templates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_create_cv_template_manifests"
down_revision: str | None = "0019_create_cv_generation_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cv_template_manifests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_asset_id", sa.Integer(), sa.ForeignKey("reference_assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("placeholders", sa.JSON(), nullable=False),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.UniqueConstraint("template_asset_id", name="uq_cv_template_manifests_asset"),
    )
    op.create_index("ix_cv_template_manifests_template_asset_id", "cv_template_manifests", ["template_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_cv_template_manifests_template_asset_id", table_name="cv_template_manifests")
    op.drop_table("cv_template_manifests")
