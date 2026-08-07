"""Add structured material JD mandate dimensions to assessments.

Revision ID: 0023_add_material_mandate_dimensions
Revises: 0022_create_cvs
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_add_material_mandate_dimensions"
down_revision = "0022_create_cvs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column(
            "material_mandate_dimensions",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("assessments", "material_mandate_dimensions")
