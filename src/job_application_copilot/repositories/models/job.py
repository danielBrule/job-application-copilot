"""SQLAlchemy persistence model for jobs."""

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain import Language, Location, UserDecision
from job_application_copilot.repositories.base import Base


def utc_now() -> datetime:
    """Return a timezone-naive UTC timestamp to whole seconds for SQLite."""

    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def enum_values[EnumMember: StrEnum](enum_type: type[EnumMember]) -> list[str]:
    """Store stable enum values rather than Python member names."""

    return [member.value for member in enum_type]


class Job(Base):
    """Locally persisted job opportunity and application tracking state."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("length(trim(company)) > 0", name="ck_jobs_company_not_blank"),
        CheckConstraint("length(trim(job_title)) > 0", name="ck_jobs_title_not_blank"),
        CheckConstraint(
            "length(trim(job_description)) > 0",
            name="ck_jobs_description_not_blank",
        ),
        CheckConstraint("length(trim(source)) > 0", name="ck_jobs_source_not_blank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[Location] = mapped_column(
        Enum(
            Location,
            name="job_location",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    language: Mapped[Language] = mapped_column(
        Enum(
            Language,
            name="job_language",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    job_url: Mapped[str | None] = mapped_column(String(2048))
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    date_added: Mapped[date] = mapped_column(Date, nullable=False)
    general_notes: Mapped[str | None] = mapped_column(Text)
    user_decision: Mapped[UserDecision] = mapped_column(
        Enum(
            UserDecision,
            name="job_user_decision",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=UserDecision.UNDECIDED,
        server_default=UserDecision.UNDECIDED.value,
    )
    application_status: Mapped[str | None] = mapped_column(Text)
    application_date: Mapped[date | None] = mapped_column(Date)
    next_action: Mapped[str | None] = mapped_column(Text)
    next_action_date: Mapped[date | None] = mapped_column(Date)
    salary_expectation: Mapped[str | None] = mapped_column(Text)
    closure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.current_timestamp(),
    )
