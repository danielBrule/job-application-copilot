"""Persistence operations for structured final CV-generation output."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import FinalCvOutput
from job_application_copilot.errors import ApplicationNotFoundError
from job_application_copilot.repositories.models import CvGenerationFinal


class CvGenerationFinalNotFoundError(ApplicationNotFoundError):
    """Raised when a task has no retained final CV."""


class CvGenerationFinalRepository:
    """Store validated stage-three output independently from raw pipeline text."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_task(self, task_id: int) -> CvGenerationFinal | None:
        return self.session.scalar(
            select(CvGenerationFinal).where(CvGenerationFinal.task_id == task_id)
        )

    def require_for_task(self, task_id: int) -> CvGenerationFinal:
        final = self.get_for_task(task_id)
        if final is None:
            raise CvGenerationFinalNotFoundError(f"CV-generation task {task_id} has no final CV.")
        return final

    def store(
        self,
        *,
        task_id: int,
        output: FinalCvOutput,
        document_a_version: int,
        document_b_version: int,
        routing_set_id: int,
        prompt_version: int,
    ) -> CvGenerationFinal:
        final = self.get_for_task(task_id)
        if final is None:
            final = CvGenerationFinal(task_id=task_id)
            self.session.add(final)
        final.document_a_version = document_a_version
        final.document_b_version = document_b_version
        final.routing_set_id = routing_set_id
        final.prompt_version = prompt_version
        final.payload = output.model_dump(mode="json")
        self.session.flush()
        return final
