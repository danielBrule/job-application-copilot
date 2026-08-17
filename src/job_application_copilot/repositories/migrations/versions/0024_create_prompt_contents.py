"""Store immutable prompt text in SQLite.

Revision ID: 0024_create_prompt_contents
Revises: 0023_add_material_mandate_dimensions
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_create_prompt_contents"
down_revision = "0023_add_material_mandate_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add prompt text storage and allow prompt assets to have no file path."""

    op.create_table(
        "prompt_contents",
        sa.Column("reference_asset_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_prompt_contents_content_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["reference_asset_id"],
            ["reference_assets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("reference_asset_id"),
    )
    with op.batch_alter_table(
        "reference_assets",
        copy_from=_reference_assets_table(prompt_file_path_nullable=False),
    ) as batch_op:
        batch_op.drop_constraint("ck_reference_assets_path_not_blank", type_="check")
        batch_op.alter_column(
            "file_path",
            existing_type=sa.String(length=2048),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "ck_reference_assets_path_not_blank",
            "(asset_type = 'PROMPT' OR file_path IS NOT NULL) "
            "AND (file_path IS NULL OR length(trim(file_path)) > 0)",
        )


def downgrade() -> None:
    """Remove SQLite prompt text storage only before any prompt body is retained."""

    stored_count = op.get_bind().execute(sa.text("SELECT count(*) FROM prompt_contents")).scalar()
    if stored_count:
        raise RuntimeError(
            "Cannot downgrade prompt-content storage after prompt text has been retained."
        )

    op.drop_table("prompt_contents")
    with op.batch_alter_table(
        "reference_assets",
        copy_from=_reference_assets_table(prompt_file_path_nullable=True),
    ) as batch_op:
        batch_op.drop_constraint("ck_reference_assets_path_not_blank", type_="check")
        batch_op.alter_column(
            "file_path",
            existing_type=sa.String(length=2048),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_reference_assets_path_not_blank",
            "length(trim(file_path)) > 0",
        )


def _reference_assets_table(*, prompt_file_path_nullable: bool) -> sa.Table:
    """Describe the batch source table so offline SQL rendering remains available."""

    metadata = sa.MetaData()
    path_constraint = (
        "(asset_type = 'PROMPT' OR file_path IS NOT NULL) "
        "AND (file_path IS NULL OR length(trim(file_path)) > 0)"
        if prompt_file_path_nullable
        else "length(trim(file_path)) > 0"
    )
    table = sa.Table(
        "reference_assets",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_key", sa.String(length=255), nullable=False),
        sa.Column("asset_type", sa.String(length=17), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("language_code", sa.String(length=16)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=prompt_file_path_nullable),
        sa.Column("file_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(length=10),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("openai_file_id", sa.String(length=255)),
        sa.Column("openai_vector_store_id", sa.String(length=255)),
        sa.Column(
            "openai_vector_store_usage_bytes",
            sa.Integer(),
            sa.CheckConstraint(
                "openai_vector_store_usage_bytes >= 0",
                name="ck_reference_assets_vector_store_usage_bytes_non_negative",
            ),
        ),
        sa.Column("processing_error", sa.String(length=2048)),
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
        sa.CheckConstraint("length(trim(asset_key)) > 0", name="ck_reference_assets_key_not_blank"),
        sa.CheckConstraint(
            "asset_type IN ('DOCUMENT', 'PROMPT', 'TEMPLATE', 'REFERENCE_EXAMPLE')",
            name="reference_asset_type",
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_reference_assets_name_not_blank"),
        sa.CheckConstraint(
            "language_code IS NULL OR length(trim(language_code)) > 0",
            name="ck_reference_assets_language_not_blank",
        ),
        sa.CheckConstraint("version > 0", name="ck_reference_assets_version_positive"),
        sa.CheckConstraint(path_constraint, name="ck_reference_assets_path_not_blank"),
        sa.CheckConstraint(
            "length(trim(file_hash)) > 0", name="ck_reference_assets_hash_not_blank"
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
        sa.CheckConstraint(
            "processing_status IN ('PENDING', 'PROCESSING', 'READY', 'FAILED')",
            name="reference_asset_processing_status",
        ),
        sa.UniqueConstraint("asset_key", "version", name="uq_reference_assets_key_version"),
    )
    sa.Index(
        "uq_reference_assets_active_key",
        table.c.asset_key,
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
    )
    return table
