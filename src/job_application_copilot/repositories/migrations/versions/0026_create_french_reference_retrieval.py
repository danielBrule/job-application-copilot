"""Create French style-reference vector source metadata.

Revision ID: 0026_create_french_reference_retrieval
Revises: 0025_retire_fourth_english_generation_prompt
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_create_french_reference_retrieval"
down_revision: str | None = "0025_retire_fourth_english_generation_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "french_reference_vector_stores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vector_store_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
    )
    op.create_table(
        "french_reference_vector_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reference_asset_id",
            sa.Integer(),
            sa.ForeignKey("reference_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vector_store_id", sa.String(length=255), nullable=False),
        sa.Column("openai_file_id", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column(
            "indexed_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.UniqueConstraint("reference_asset_id", name="uq_french_reference_vector_source_asset"),
        sa.UniqueConstraint("openai_file_id", name="uq_french_reference_vector_source_openai_file"),
    )
    op.create_index(
        "ix_french_reference_vector_sources_reference_asset_id",
        "french_reference_vector_sources",
        ["reference_asset_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_french_reference_vector_sources_reference_asset_id")
    op.drop_table("french_reference_vector_sources")
    op.drop_table("french_reference_vector_stores")
