"""Create the current structured assessment model."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_create_assessments"
down_revision: str | None = "0013_create_llm_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add assessment-input tracking and one current assessment per job."""

    op.add_column(
        "jobs",
        sa.Column(
            "assessment_input_updated_at",
            sa.DateTime(),
            server_default=sa.text("'1970-01-01 00:00:00'"),
            nullable=False,
        ),
    )

    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("model_relevance", sa.String(length=6), nullable=True),
        sa.Column("role_snapshot", sa.Text(), nullable=True),
        sa.Column("real_mandate", sa.Text(), nullable=True),
        sa.Column("primary_role_family", sa.String(length=255), nullable=True),
        sa.Column("secondary_role_family", sa.String(length=255), nullable=True),
        sa.Column("seniority_fit", sa.Integer(), nullable=True),
        sa.Column("technical_bar", sa.Text(), nullable=True),
        sa.Column("tech_bar_fit", sa.Integer(), nullable=True),
        sa.Column("fit_score", sa.Integer(), nullable=True),
        sa.Column("priority_score", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("interview_probability_low", sa.Integer(), nullable=True),
        sa.Column("interview_probability_high", sa.Integer(), nullable=True),
        sa.Column("interview_probability_confidence", sa.Integer(), nullable=True),
        sa.Column("strong_fit_signals", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("red_flags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "sustainability_risks", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column("evidence_gaps", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("evidence_anchors", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("evidence_confidence", sa.Integer(), nullable=True),
        sa.Column("recommended_document_b_lane", sa.String(length=128), nullable=True),
        sa.Column("selected_cv_lane", sa.String(length=128), nullable=True),
        sa.Column("secondary_cv_angle", sa.Text(), nullable=True),
        sa.Column(
            "overclaiming_risks",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("assessment_notes", sa.Text(), nullable=True),
        sa.Column("document_a_version", sa.Integer(), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("assessed_at", sa.DateTime(), nullable=True),
        sa.Column("source_job_updated_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.UniqueConstraint("job_id", name="uq_assessments_job_id"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'ASSESSED', 'FAILED')",
            name="assessment_status",
        ),
        sa.CheckConstraint(
            "model_relevance IS NULL OR model_relevance IN ('HIGH', 'MEDIUM', 'LOW')",
            name="assessment_model_relevance",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('GO', 'CAUTION', 'STRETCH', 'NO_GO')",
            name="assessment_decision",
        ),
        sa.CheckConstraint(
            "seniority_fit IS NULL OR seniority_fit BETWEEN 0 AND 10",
            name="ck_assessments_seniority_fit_range",
        ),
        sa.CheckConstraint(
            "tech_bar_fit IS NULL OR tech_bar_fit BETWEEN 0 AND 10",
            name="ck_assessments_tech_bar_fit_range",
        ),
        sa.CheckConstraint(
            "fit_score IS NULL OR fit_score BETWEEN 0 AND 10",
            name="ck_assessments_fit_score_range",
        ),
        sa.CheckConstraint(
            "priority_score IS NULL OR priority_score BETWEEN 0 AND 10",
            name="ck_assessments_priority_score_range",
        ),
        sa.CheckConstraint(
            "interview_probability_low IS NULL OR interview_probability_low BETWEEN 0 AND 10",
            name="ck_assessments_interview_probability_low_range",
        ),
        sa.CheckConstraint(
            "interview_probability_high IS NULL OR interview_probability_high BETWEEN 0 AND 10",
            name="ck_assessments_interview_probability_high_range",
        ),
        sa.CheckConstraint(
            "interview_probability_confidence IS NULL "
            "OR interview_probability_confidence BETWEEN 0 AND 10",
            name="ck_assessments_interview_probability_confidence_range",
        ),
        sa.CheckConstraint(
            "evidence_confidence IS NULL OR evidence_confidence BETWEEN 0 AND 10",
            name="ck_assessments_evidence_confidence_range",
        ),
        sa.CheckConstraint(
            "interview_probability_low IS NULL OR interview_probability_high IS NULL "
            "OR interview_probability_low <= interview_probability_high",
            name="ck_assessments_interview_probability_order",
        ),
        sa.CheckConstraint(
            "(status = 'FAILED' AND error_message IS NOT NULL) "
            "OR (status != 'FAILED' AND error_message IS NULL)",
            name="ck_assessments_error_matches_status",
        ),
        sa.CheckConstraint(
            "assessed_at IS NULL OR status = 'ASSESSED'",
            name="ck_assessments_assessed_at_matches_status",
        ),
        sa.CheckConstraint(
            "status != 'ASSESSED' OR ("
            "model_relevance IS NOT NULL "
            "AND role_snapshot IS NOT NULL AND length(trim(role_snapshot)) > 0 "
            "AND real_mandate IS NOT NULL AND length(trim(real_mandate)) > 0 "
            "AND primary_role_family IS NOT NULL "
            "AND length(trim(primary_role_family)) > 0 "
            "AND secondary_role_family IS NOT NULL "
            "AND length(trim(secondary_role_family)) > 0 "
            "AND fit_score IS NOT NULL "
            "AND priority_score IS NOT NULL "
            "AND technical_bar IS NOT NULL AND length(trim(technical_bar)) > 0 "
            "AND seniority_fit IS NOT NULL "
            "AND decision IS NOT NULL "
            "AND decision_reason IS NOT NULL AND length(trim(decision_reason)) > 0 "
            "AND recommended_document_b_lane IS NOT NULL "
            "AND assessed_at IS NOT NULL "
            "AND source_job_updated_at IS NOT NULL)",
            name="ck_assessments_assessed_fields_complete",
        ),
    )
    op.create_index("ix_assessments_job_id", "assessments", ["job_id"])


def downgrade() -> None:
    """Remove current assessments and their job-input timestamp."""

    op.drop_index("ix_assessments_job_id", table_name="assessments")
    op.drop_table("assessments")
    op.drop_column("jobs", "assessment_input_updated_at")
