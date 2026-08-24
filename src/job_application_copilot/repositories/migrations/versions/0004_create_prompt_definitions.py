"""Create and seed data-driven prompt definitions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_create_prompt_definitions"
down_revision: str | None = "0003_create_reference_assets_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INITIAL_PROMPT_DEFINITIONS = (
    {
        "asset_key": "assessment",
        "name": "Assessment prompt",
        "pipeline_group": "assessment",
        "language_code": None,
        "position": 1,
    },
    *(
        {
            "asset_key": f"cv-generation-en-stage-{position}",
            "name": f"English generation prompt {position}",
            "pipeline_group": "generation/english",
            "language_code": "en",
            "position": position,
        }
        for position in range(1, 4)
    ),
    *(
        {
            "asset_key": f"cv-generation-fr-extension-{position}",
            "name": f"French extension prompt {position}",
            "pipeline_group": "generation/french",
            "language_code": "fr",
            "position": position,
        }
        for position in range(1, 3)
    ),
)


def upgrade() -> None:
    """Create prompt definitions and seed the initial required configuration."""

    table = op.create_table(
        "prompt_definitions",
        sa.Column("asset_key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("pipeline_group", sa.String(length=255), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
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
            name="ck_prompt_definitions_key_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_prompt_definitions_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(pipeline_group)) > 0",
            name="ck_prompt_definitions_group_not_blank",
        ),
        sa.CheckConstraint(
            "language_code IS NULL OR length(trim(language_code)) > 0",
            name="ck_prompt_definitions_language_not_blank",
        ),
        sa.CheckConstraint(
            "language_code IS NULL OR language_code = lower(language_code)",
            name="ck_prompt_definitions_language_lowercase",
        ),
        sa.CheckConstraint(
            "position > 0",
            name="ck_prompt_definitions_position_positive",
        ),
        sa.PrimaryKeyConstraint("asset_key"),
        sa.UniqueConstraint(
            "pipeline_group",
            "position",
            name="uq_prompt_definitions_group_position",
        ),
    )
    op.bulk_insert(table, list(INITIAL_PROMPT_DEFINITIONS))


def downgrade() -> None:
    """Remove prompt definitions while retaining reference-asset versions."""

    op.drop_table("prompt_definitions")
