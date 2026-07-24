"""Create the jobs table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_create_jobs_table"
down_revision: str | None = "0001_database_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persisted job and application-tracking fields."""

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("job_title", sa.String(length=255), nullable=False),
        sa.Column(
            "location",
            sa.Enum(
                "UK",
                "FR",
                "CH",
                name="job_location",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "language",
            sa.Enum(
                "EN",
                "FR",
                name="job_language",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("job_url", sa.String(length=2048), nullable=True),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column(
            "date_added",
            sa.Date(),
            nullable=False,
        ),
        sa.Column("general_notes", sa.Text(), nullable=True),
        sa.Column(
            "user_decision",
            sa.Enum(
                "UNDECIDED",
                "PURSUE",
                "DO_NOT_PURSUE",
                name="job_user_decision",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'UNDECIDED'"),
            nullable=False,
        ),
        sa.Column("application_status", sa.Text(), nullable=True),
        sa.Column("application_date", sa.Date(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("next_action_date", sa.Date(), nullable=True),
        sa.Column("salary_expectation", sa.Text(), nullable=True),
        sa.Column("closure_reason", sa.Text(), nullable=True),
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
            "length(trim(company)) > 0",
            name="ck_jobs_company_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(job_title)) > 0",
            name="ck_jobs_title_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(job_description)) > 0",
            name="ck_jobs_description_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(source)) > 0",
            name="ck_jobs_source_not_blank",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Remove the jobs table."""

    op.drop_table("jobs")
