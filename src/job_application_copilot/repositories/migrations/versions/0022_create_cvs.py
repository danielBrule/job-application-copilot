"""Create one current CV record for each job."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_create_cvs"
down_revision: str | None = "0021_create_cv_generation_finals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cvs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("file_name", sa.String(length=255)),
        sa.Column("file_path", sa.String(length=2048)),
        sa.Column("selected_cv_lane", sa.String(length=255)),
        sa.Column("document_a_version", sa.Integer()),
        sa.Column("document_b_version", sa.Integer()),
        sa.Column("template_version", sa.Integer()),
        sa.Column("generation_prompt_versions", sa.JSON()),
        sa.Column("french_prompt_versions", sa.JSON()),
        sa.Column("review_notes", sa.Text()),
        sa.Column("generated_or_uploaded_at", sa.DateTime()),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(file_name)) > 0 OR file_name IS NULL", name="ck_cvs_name_not_blank"
        ),
        sa.CheckConstraint(
            "length(trim(file_path)) > 0 OR file_path IS NULL", name="ck_cvs_path_not_blank"
        ),
        sa.CheckConstraint("source IN ('GENERATED', 'UPLOADED')", name="cv_source"),
        sa.CheckConstraint(
            "status IN ('SELECTED', 'PENDING', 'GENERATING', 'READY_FOR_REVIEW', 'FAILED', 'APPROVED')",
            name="cv_status",
        ),
        sa.CheckConstraint("language IN ('EN', 'FR')", name="cv_language"),
        sa.CheckConstraint(
            "status NOT IN ('READY_FOR_REVIEW', 'APPROVED') "
            "OR (file_name IS NOT NULL AND file_path IS NOT NULL)",
            name="ck_cvs_ready_requires_file",
        ),
        sa.CheckConstraint(
            "(status = 'APPROVED' AND approved_at IS NOT NULL) "
            "OR (status != 'APPROVED' AND approved_at IS NULL)",
            name="ck_cvs_approval_matches_status",
        ),
        sa.CheckConstraint(
            "(status = 'FAILED' AND error_message IS NOT NULL AND length(trim(error_message)) > 0) "
            "OR (status != 'FAILED' AND error_message IS NULL)",
            name="ck_cvs_error_matches_status",
        ),
        sa.UniqueConstraint("job_id", name="uq_cvs_job"),
    )
    op.create_index("ix_cvs_job_id", "cvs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_cvs_job_id", table_name="cvs")
    op.drop_table("cvs")
