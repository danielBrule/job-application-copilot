"""Allow completed assessments without a secondary role family."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_optional_secondary_role_family"
down_revision: str | None = "0014_create_assessments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMPLETE_ASSESSMENT_WITH_OPTIONAL_SECONDARY = (
    "status != 'ASSESSED' OR ("
    "model_relevance IS NOT NULL "
    "AND role_snapshot IS NOT NULL AND length(trim(role_snapshot)) > 0 "
    "AND real_mandate IS NOT NULL AND length(trim(real_mandate)) > 0 "
    "AND primary_role_family IS NOT NULL "
    "AND length(trim(primary_role_family)) > 0 "
    "AND fit_score IS NOT NULL "
    "AND priority_score IS NOT NULL "
    "AND technical_bar IS NOT NULL AND length(trim(technical_bar)) > 0 "
    "AND seniority_fit IS NOT NULL "
    "AND decision IS NOT NULL "
    "AND decision_reason IS NOT NULL AND length(trim(decision_reason)) > 0 "
    "AND recommended_document_b_lane IS NOT NULL "
    "AND assessed_at IS NOT NULL "
    "AND source_job_updated_at IS NOT NULL)"
)

COMPLETE_ASSESSMENT_WITH_REQUIRED_SECONDARY = (
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
    "AND source_job_updated_at IS NOT NULL)"
)


def upgrade() -> None:
    """Make the secondary family nullable for otherwise complete assessments."""

    with op.batch_alter_table(
        "assessments",
        copy_from=_assessment_table(require_secondary=True),
    ) as batch_op:
        batch_op.drop_constraint(
            "ck_assessments_assessed_fields_complete",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_assessments_secondary_role_family_not_blank",
            "secondary_role_family IS NULL OR length(trim(secondary_role_family)) > 0",
        )
        batch_op.create_check_constraint(
            "ck_assessments_assessed_fields_complete",
            COMPLETE_ASSESSMENT_WITH_OPTIONAL_SECONDARY,
        )


def downgrade() -> None:
    """Restore the original completed-assessment requirement."""

    with op.batch_alter_table(
        "assessments",
        copy_from=_assessment_table(require_secondary=False),
    ) as batch_op:
        batch_op.drop_constraint(
            "ck_assessments_assessed_fields_complete",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_assessments_secondary_role_family_not_blank",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_assessments_assessed_fields_complete",
            COMPLETE_ASSESSMENT_WITH_REQUIRED_SECONDARY,
        )


def _assessment_table(*, require_secondary: bool) -> sa.Table:
    """Describe the source table so SQLite batch mode also works offline."""

    metadata = sa.MetaData()
    constraints: list[sa.Constraint] = [
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
            (
                COMPLETE_ASSESSMENT_WITH_REQUIRED_SECONDARY
                if require_secondary
                else COMPLETE_ASSESSMENT_WITH_OPTIONAL_SECONDARY
            ),
            name="ck_assessments_assessed_fields_complete",
        ),
    ]
    if not require_secondary:
        constraints.append(
            sa.CheckConstraint(
                "secondary_role_family IS NULL OR length(trim(secondary_role_family)) > 0",
                name="ck_assessments_secondary_role_family_not_blank",
            )
        )
    table = sa.Table(
        "assessments",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("model_relevance", sa.String(length=6)),
        sa.Column("role_snapshot", sa.Text()),
        sa.Column("real_mandate", sa.Text()),
        sa.Column("primary_role_family", sa.String(length=255)),
        sa.Column("secondary_role_family", sa.String(length=255)),
        sa.Column("seniority_fit", sa.Integer()),
        sa.Column("technical_bar", sa.Text()),
        sa.Column("tech_bar_fit", sa.Integer()),
        sa.Column("fit_score", sa.Integer()),
        sa.Column("priority_score", sa.Integer()),
        sa.Column("decision", sa.String(length=16)),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("interview_probability_low", sa.Integer()),
        sa.Column("interview_probability_high", sa.Integer()),
        sa.Column("interview_probability_confidence", sa.Integer()),
        sa.Column("strong_fit_signals", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("red_flags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "sustainability_risks",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("evidence_gaps", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("evidence_anchors", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("evidence_confidence", sa.Integer()),
        sa.Column("recommended_document_b_lane", sa.String(length=128)),
        sa.Column("selected_cv_lane", sa.String(length=128)),
        sa.Column("secondary_cv_angle", sa.Text()),
        sa.Column(
            "overclaiming_risks",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("assessment_notes", sa.Text()),
        sa.Column("document_a_version", sa.Integer()),
        sa.Column("prompt_version", sa.Integer()),
        sa.Column("model_name", sa.String(length=128)),
        sa.Column("assessed_at", sa.DateTime()),
        sa.Column("source_job_updated_at", sa.DateTime()),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        *constraints,
    )
    sa.Index("ix_assessments_job_id", table.c.job_id)
    return table
