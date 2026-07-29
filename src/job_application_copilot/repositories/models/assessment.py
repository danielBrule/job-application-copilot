"""SQLAlchemy persistence model for a job's current assessment."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    CvLane,
    Relevance,
)
from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import enum_values, utc_now


class Assessment(Base):
    """The single current structured assessment for one job."""

    __tablename__ = "assessments"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_assessments_job_id"),
        CheckConstraint(
            "seniority_fit IS NULL OR seniority_fit BETWEEN 0 AND 10",
            name="ck_assessments_seniority_fit_range",
        ),
        CheckConstraint(
            "tech_bar_fit IS NULL OR tech_bar_fit BETWEEN 0 AND 10",
            name="ck_assessments_tech_bar_fit_range",
        ),
        CheckConstraint(
            "fit_score IS NULL OR fit_score BETWEEN 0 AND 10",
            name="ck_assessments_fit_score_range",
        ),
        CheckConstraint(
            "priority_score IS NULL OR priority_score BETWEEN 0 AND 10",
            name="ck_assessments_priority_score_range",
        ),
        CheckConstraint(
            "interview_probability_low IS NULL OR interview_probability_low BETWEEN 0 AND 10",
            name="ck_assessments_interview_probability_low_range",
        ),
        CheckConstraint(
            "interview_probability_high IS NULL OR interview_probability_high BETWEEN 0 AND 10",
            name="ck_assessments_interview_probability_high_range",
        ),
        CheckConstraint(
            "interview_probability_confidence IS NULL "
            "OR interview_probability_confidence BETWEEN 0 AND 10",
            name="ck_assessments_interview_probability_confidence_range",
        ),
        CheckConstraint(
            "evidence_confidence IS NULL OR evidence_confidence BETWEEN 0 AND 10",
            name="ck_assessments_evidence_confidence_range",
        ),
        CheckConstraint(
            "interview_probability_low IS NULL OR interview_probability_high IS NULL "
            "OR interview_probability_low <= interview_probability_high",
            name="ck_assessments_interview_probability_order",
        ),
        CheckConstraint(
            "(status = 'FAILED' AND error_message IS NOT NULL) "
            "OR (status != 'FAILED' AND error_message IS NULL)",
            name="ck_assessments_error_matches_status",
        ),
        CheckConstraint(
            "assessed_at IS NULL OR status = 'ASSESSED'",
            name="ck_assessments_assessed_at_matches_status",
        ),
        CheckConstraint(
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

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[AssessmentStatus] = mapped_column(
        Enum(
            AssessmentStatus,
            name="assessment_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=AssessmentStatus.PENDING,
        server_default=AssessmentStatus.PENDING.value,
    )
    model_relevance: Mapped[Relevance | None] = mapped_column(
        Enum(
            Relevance,
            name="assessment_model_relevance",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        )
    )
    role_snapshot: Mapped[str | None] = mapped_column(Text)
    real_mandate: Mapped[str | None] = mapped_column(Text)
    primary_role_family: Mapped[str | None] = mapped_column(String(255))
    secondary_role_family: Mapped[str | None] = mapped_column(String(255))
    seniority_fit: Mapped[int | None] = mapped_column(Integer)
    technical_bar: Mapped[str | None] = mapped_column(Text)
    tech_bar_fit: Mapped[int | None] = mapped_column(Integer)
    fit_score: Mapped[int | None] = mapped_column(Integer)
    priority_score: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[AssessmentDecision | None] = mapped_column(
        Enum(
            AssessmentDecision,
            name="assessment_decision",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        )
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)
    interview_probability_low: Mapped[int | None] = mapped_column(Integer)
    interview_probability_high: Mapped[int | None] = mapped_column(Integer)
    interview_probability_confidence: Mapped[int | None] = mapped_column(Integer)
    strong_fit_signals: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    red_flags: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    sustainability_risks: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    evidence_gaps: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    evidence_anchors: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    evidence_confidence: Mapped[int | None] = mapped_column(Integer)
    recommended_document_b_lane: Mapped[CvLane | None] = mapped_column(
        Enum(
            CvLane,
            name="assessment_recommended_document_b_lane",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        )
    )
    selected_cv_lane: Mapped[CvLane | None] = mapped_column(
        Enum(
            CvLane,
            name="assessment_selected_cv_lane",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        )
    )
    secondary_cv_angle: Mapped[str | None] = mapped_column(Text)
    overclaiming_risks: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    assessment_notes: Mapped[str | None] = mapped_column(Text)
    document_a_version: Mapped[int | None] = mapped_column(Integer)
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    model_name: Mapped[str | None] = mapped_column(String(128))
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_job_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )
