"""Persistence operations for structured CV-generation drafts."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import CvGenerationDraftOutput
from job_application_copilot.errors import ApplicationNotFoundError
from job_application_copilot.repositories.models import CvGenerationDraft


class CvGenerationDraftNotFoundError(ApplicationNotFoundError):
    """Raised when a task has no retained stage-two draft."""


class CvGenerationDraftRepository:
    """Store validated stage-two output independently from raw pipeline text."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_task(self, task_id: int) -> CvGenerationDraft | None:
        return self.session.scalar(
            select(CvGenerationDraft).where(CvGenerationDraft.task_id == task_id)
        )

    def require_for_task(self, task_id: int) -> CvGenerationDraft:
        draft = self.get_for_task(task_id)
        if draft is None:
            raise CvGenerationDraftNotFoundError(f"CV-generation task {task_id} has no draft.")
        return draft

    def store(
        self,
        *,
        task_id: int,
        output: CvGenerationDraftOutput,
        document_a_version: int,
        document_b_version: int,
        routing_set_id: int,
        prompt_version: int,
    ) -> CvGenerationDraft:
        draft = self.get_for_task(task_id)
        if draft is None:
            draft = CvGenerationDraft(task_id=task_id)
            self.session.add(draft)
        draft.document_a_version = document_a_version
        draft.document_b_version = document_b_version
        draft.routing_set_id = routing_set_id
        draft.prompt_version = prompt_version
        draft.payload = output.model_dump(mode="json")
        self.session.flush()
        return draft
