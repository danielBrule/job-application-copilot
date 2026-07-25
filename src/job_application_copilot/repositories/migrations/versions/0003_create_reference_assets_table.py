"""Create the reference-assets table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_create_reference_assets_table"
down_revision: str | None = "0002_create_jobs_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create versioned reference-asset metadata and active-version constraints."""

    op.create_table(
        "reference_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_key", sa.String(length=255), nullable=False),
        sa.Column(
            "asset_type",
            sa.Enum(
                "DOCUMENT",
                "PROMPT",
                "TEMPLATE",
                "REFERENCE_EXAMPLE",
                name="reference_asset_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column("file_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "processing_status",
            sa.Enum(
                "PENDING",
                "PROCESSING",
                "READY",
                "FAILED",
                name="reference_asset_processing_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("openai_file_id", sa.String(length=255), nullable=True),
        sa.Column(
            "openai_vector_store_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(asset_key)) > 0",
            name="ck_reference_assets_key_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_reference_assets_name_not_blank",
        ),
        sa.CheckConstraint(
            "language_code IS NULL OR length(trim(language_code)) > 0",
            name="ck_reference_assets_language_not_blank",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_reference_assets_version_positive",
        ),
        sa.CheckConstraint(
            "length(trim(file_path)) > 0",
            name="ck_reference_assets_path_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(file_hash)) > 0",
            name="ck_reference_assets_hash_not_blank",
        ),
        sa.CheckConstraint(
            "openai_file_id IS NULL OR length(trim(openai_file_id)) > 0",
            name="ck_reference_assets_openai_file_id_not_blank",
        ),
        sa.CheckConstraint(
            "openai_vector_store_id IS NULL OR length(trim(openai_vector_store_id)) > 0",
            name="ck_reference_assets_vector_store_id_not_blank",
        ),
        sa.CheckConstraint(
            "is_active = 0 OR processing_status = 'READY'",
            name="ck_reference_assets_active_ready",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_key",
            "version",
            name="uq_reference_assets_key_version",
        ),
    )
    op.create_index(
        "uq_reference_assets_active_key",
        "reference_assets",
        ["asset_key"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
    )


def downgrade() -> None:
    """Remove reference-asset metadata."""

    op.drop_index(
        "uq_reference_assets_active_key",
        table_name="reference_assets",
        sqlite_where=sa.text("is_active = 1"),
    )
    op.drop_table("reference_assets")
