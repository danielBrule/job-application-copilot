"""Persistence operations for structured CV-generation briefs."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import CvGenerationBriefOutput
from job_application_copilot.errors import ApplicationNotFoundError
from job_application_copilot.repositories.models import CvGenerationBrief


class CvGenerationBriefNotFoundError(ApplicationNotFoundError):
    """Raised when a task has no retained stage-one brief."""


class CvGenerationBriefRepository:
    """Store validated stage-one output independently from raw pipeline text."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_task(self, task_id: int) -> CvGenerationBrief | None:
        return self.session.scalar(
            select(CvGenerationBrief).where(CvGenerationBrief.task_id == task_id)
        )

    def require_for_task(self, task_id: int) -> CvGenerationBrief:
        brief = self.get_for_task(task_id)
        if brief is None:
            raise CvGenerationBriefNotFoundError(f"CV-generation task {task_id} has no brief.")
        return brief

    def store(
        self,
        *,
        task_id: int,
        output: CvGenerationBriefOutput,
        document_a_version: int,
        document_b_version: int,
        routing_set_id: int,
        prompt_version: int,
    ) -> CvGenerationBrief:
        brief = self.get_for_task(task_id)
        if brief is None:
            brief = CvGenerationBrief(task_id=task_id)
            self.session.add(brief)
        brief.target_cv_lane = output.target_cv_lane
        brief.document_a_version = document_a_version
        brief.document_b_version = document_b_version
        brief.routing_set_id = routing_set_id
        brief.prompt_version = prompt_version
        brief.payload = output.model_dump(mode="json")
        self.session.flush()
        return brief
