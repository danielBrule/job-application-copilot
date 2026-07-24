"""Establish the controlled database migration baseline."""

from collections.abc import Sequence

revision: str = "0001_database_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create no domain tables in the foundation migration."""


def downgrade() -> None:
    """Remove no domain tables from the foundation migration."""
