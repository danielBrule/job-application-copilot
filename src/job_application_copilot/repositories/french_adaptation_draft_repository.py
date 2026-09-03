"""Persistence operations for the first structured French adaptation output."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import FinalCvOutput
from job_application_copilot.errors import ApplicationNotFoundError
from job_application_copilot.repositories.models import FrenchAdaptationDraft


class FrenchAdaptationDraftNotFoundError(ApplicationNotFoundError):
    """Raised when a task has no retained French adaptation draft."""


class FrenchAdaptationDraftRepository:
    """Store validated French prompt-one output independently from raw pipeline text."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_task(self, task_id: int) -> FrenchAdaptationDraft | None:
        return self.session.scalar(
            select(FrenchAdaptationDraft).where(FrenchAdaptationDraft.task_id == task_id)
        )

    def require_for_task(self, task_id: int) -> FrenchAdaptationDraft:
        draft = self.get_for_task(task_id)
        if draft is None:
            raise FrenchAdaptationDraftNotFoundError(
                f"CV-generation task {task_id} has no French adaptation draft."
            )
        return draft

    def store(
        self,
        *,
        task_id: int,
        output: FinalCvOutput,
        target_locale: str,
        document_a_version: int,
        document_b_version: int,
        english_final_prompt_version: int,
        french_prompt_version: int,
        english_template_version: int,
        french_template_version: int,
        french_reference_versions: tuple[str, ...],
    ) -> FrenchAdaptationDraft:
        draft = self.get_for_task(task_id)
        if draft is None:
            draft = FrenchAdaptationDraft(task_id=task_id)
            self.session.add(draft)
        draft.target_locale = target_locale
        draft.document_a_version = document_a_version
        draft.document_b_version = document_b_version
        draft.english_final_prompt_version = english_final_prompt_version
        draft.french_prompt_version = french_prompt_version
        draft.english_template_version = english_template_version
        draft.french_template_version = french_template_version
        draft.french_reference_versions = list(french_reference_versions)
        draft.payload = output.model_dump(mode="json")
        self.session.flush()
        return draft
