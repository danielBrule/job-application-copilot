"""Global Jobs dashboard usage and processing KPI aggregation."""

from dataclasses import dataclass

from sqlalchemy import func, or_, select

from job_application_copilot.domain import (
    AssessmentStatus,
    BackgroundOperation,
    CvSource,
    CvStatus,
    LlmUsageTotals,
    UserDecision,
)
from job_application_copilot.repositories import Database, LlmCallRepository
from job_application_copilot.repositories.models import Assessment, Cv, Job


@dataclass(frozen=True, slots=True)
class OperationUsageKpis:
    """Token and duration KPIs for one logical operation."""

    total_tokens: int
    average_tokens_per_successful_call: float | None
    total_duration_seconds: float
    average_duration_seconds_per_successful_call: float | None

    @classmethod
    def from_totals(cls, totals: LlmUsageTotals | None) -> "OperationUsageKpis":
        """Calculate averages only when one or more calls succeeded."""

        if totals is None:
            return cls(0, None, 0.0, None)
        successful_calls = totals.succeeded_count
        return cls(
            total_tokens=totals.total_tokens,
            average_tokens_per_successful_call=(
                totals.successful_total_tokens / successful_calls if successful_calls else None
            ),
            total_duration_seconds=totals.duration_seconds,
            average_duration_seconds_per_successful_call=(
                totals.successful_duration_seconds / successful_calls if successful_calls else None
            ),
        )


@dataclass(frozen=True, slots=True)
class DashboardUsageKpis:
    """Usage and processing KPIs split by dashboard operation."""

    assessment: OperationUsageKpis
    cv_generation: OperationUsageKpis


@dataclass(frozen=True, slots=True)
class DashboardWorkflowKpis:
    jobs_entered: int
    assessed_jobs_awaiting_review: int
    generated_cvs_awaiting_application: int


class DashboardKpiService:
    """Aggregate global dashboard KPIs outside Streamlit page code."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def usage(self) -> DashboardUsageKpis:
        """Return current global usage and duration KPIs."""

        with self.database.session() as session:
            totals = LlmCallRepository(session).aggregate_dashboard()
        return DashboardUsageKpis(
            assessment=OperationUsageKpis.from_totals(totals.get(BackgroundOperation.ASSESSMENT)),
            cv_generation=OperationUsageKpis.from_totals(
                totals.get(BackgroundOperation.CV_GENERATION)
            ),
        )

    def workflow(self) -> DashboardWorkflowKpis:
        with self.database.session() as session:
            return DashboardWorkflowKpis(
                jobs_entered=session.scalar(select(func.count()).select_from(Job)) or 0,
                assessed_jobs_awaiting_review=session.scalar(
                    select(func.count())
                    .select_from(Assessment)
                    .join(Job, Job.id == Assessment.job_id)
                    .where(
                        Assessment.status == AssessmentStatus.ASSESSED,
                        Job.user_decision == UserDecision.UNDECIDED,
                    )
                )
                or 0,
                generated_cvs_awaiting_application=session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .join(Cv, Cv.job_id == Job.id)
                    .where(
                        or_(
                            Job.application_status.is_(None),
                            func.trim(Job.application_status) == "",
                        ),
                        Cv.source == CvSource.GENERATED,
                        Cv.status.in_((CvStatus.READY_FOR_REVIEW, CvStatus.APPROVED)),
                    )
                )
                or 0,
            )
