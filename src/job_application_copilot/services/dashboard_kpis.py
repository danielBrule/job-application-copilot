"""Global Jobs dashboard usage and processing KPI aggregation."""

from dataclasses import dataclass

from sqlalchemy import func, or_, select

from job_application_copilot.domain import (
    AssessmentStatus,
    BackgroundOperation,
    CvSelectionStatus,
    CvSource,
    CvStatus,
    LlmUsageTotals,
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
    assessed_jobs: int
    applied_jobs: int
    unassessed_jobs: int
    selected_jobs_without_generated_cv: int


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
                assessed_jobs=session.scalar(
                    select(func.count())
                    .select_from(Assessment)
                    .where(Assessment.status == AssessmentStatus.ASSESSED)
                )
                or 0,
                applied_jobs=session.scalar(
                    select(func.count()).select_from(Job).where(Job.application_status == "Applied")
                )
                or 0,
                unassessed_jobs=session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .outerjoin(Assessment, Assessment.job_id == Job.id)
                    .where(
                        or_(
                            Assessment.id.is_(None),
                            Assessment.status != AssessmentStatus.ASSESSED,
                        )
                    )
                )
                or 0,
                selected_jobs_without_generated_cv=session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .outerjoin(Cv, Cv.job_id == Job.id)
                    .where(
                        Job.cv_selection_status == CvSelectionStatus.SELECTED,
                        or_(
                            Cv.id.is_(None),
                            Cv.source != CvSource.GENERATED,
                            Cv.status.not_in((CvStatus.READY_FOR_REVIEW, CvStatus.APPROVED)),
                        ),
                    )
                )
                or 0,
            )
