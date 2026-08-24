"""Retire the legacy fourth English CV-generation prompt definition.

Revision ID: 0025_retire_fourth_english_generation_prompt
Revises: 0024_create_prompt_contents
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_retire_fourth_english_generation_prompt"
down_revision: str | None = "0024_create_prompt_contents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_ASSET_KEY = "cv-generation-en-stage-4"


def upgrade() -> None:
    """Remove only the obsolete definition, retaining any stored prompt versions."""

    op.execute(
        sa.text("DELETE FROM prompt_definitions WHERE asset_key = :asset_key").bindparams(
            asset_key=LEGACY_ASSET_KEY
        )
    )


def downgrade() -> None:
    """Restore the legacy definition without altering retained prompt versions."""

    op.bulk_insert(
        sa.table(
            "prompt_definitions",
            sa.column("asset_key", sa.String),
            sa.column("name", sa.String),
            sa.column("pipeline_group", sa.String),
            sa.column("language_code", sa.String),
            sa.column("position", sa.Integer),
            sa.column("is_enabled", sa.Boolean),
        ),
        [
            {
                "asset_key": LEGACY_ASSET_KEY,
                "name": "English generation prompt 4",
                "pipeline_group": "generation/english",
                "language_code": "en",
                "position": 4,
                "is_enabled": True,
            }
        ],
    )
