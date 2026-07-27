"""Create locally extracted Document B sections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_create_document_b_sections"
down_revision: str | None = "0006_add_reference_asset_vector_store_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create version-bound, deterministically ordered Document B sections."""

    op.create_table(
        "document_b_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reference_asset_id",
            sa.Integer(),
            sa.ForeignKey("reference_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_id", sa.String(length=255), nullable=False),
        sa.Column("heading_number", sa.String(length=64), nullable=True),
        sa.Column("heading_title", sa.String(length=512), nullable=False),
        sa.Column("heading_level", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("section_text", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(trim(section_id)) > 0",
            name="ck_document_b_sections_id_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(heading_title)) > 0",
            name="ck_document_b_sections_title_not_blank",
        ),
        sa.CheckConstraint(
            "heading_level >= 0",
            name="ck_document_b_sections_level_non_negative",
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_document_b_sections_sequence_positive",
        ),
        sa.UniqueConstraint(
            "reference_asset_id",
            "section_id",
            name="uq_document_b_sections_asset_section_id",
        ),
        sa.UniqueConstraint(
            "reference_asset_id",
            "sequence",
            name="uq_document_b_sections_asset_sequence",
        ),
    )
    op.create_index(
        "ix_document_b_sections_reference_asset_id",
        "document_b_sections",
        ["reference_asset_id"],
    )


def downgrade() -> None:
    """Remove extracted Document B sections."""

    op.drop_index(
        "ix_document_b_sections_reference_asset_id",
        table_name="document_b_sections",
    )
    op.drop_table("document_b_sections")
