"""Persistence operations for reviewed French CV output."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import FinalCvOutput
from job_application_copilot.errors import ApplicationNotFoundError
from job_application_copilot.repositories.models import FrenchAdaptationFinal


class FrenchAdaptationFinalNotFoundError(ApplicationNotFoundError):
    """Raised when a task has no retained reviewed French CV."""


class FrenchAdaptationFinalRepository:
    """Store validated French prompt-two output independently from its draft."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_task(self, task_id: int) -> FrenchAdaptationFinal | None:
        return self.session.scalar(
            select(FrenchAdaptationFinal).where(FrenchAdaptationFinal.task_id == task_id)
        )

    def require_for_task(self, task_id: int) -> FrenchAdaptationFinal:
        final = self.get_for_task(task_id)
        if final is None:
            raise FrenchAdaptationFinalNotFoundError(
                f"CV-generation task {task_id} has no reviewed French CV."
            )
        return final

    def store(
        self,
        *,
        task_id: int,
        output: FinalCvOutput,
        target_locale: str,
        document_a_version: int,
        document_b_version: int,
        english_final_prompt_version: int,
        french_adaptation_prompt_version: int,
        french_review_prompt_version: int,
        english_template_version: int,
        french_template_version: int,
        french_reference_versions: tuple[str, ...],
    ) -> FrenchAdaptationFinal:
        final = self.get_for_task(task_id)
        if final is None:
            final = FrenchAdaptationFinal(task_id=task_id)
            self.session.add(final)
        final.target_locale = target_locale
        final.document_a_version = document_a_version
        final.document_b_version = document_b_version
        final.english_final_prompt_version = english_final_prompt_version
        final.french_adaptation_prompt_version = french_adaptation_prompt_version
        final.french_review_prompt_version = french_review_prompt_version
        final.english_template_version = english_template_version
        final.french_template_version = french_template_version
        final.french_reference_versions = list(french_reference_versions)
        final.payload = output.model_dump(mode="json")
        self.session.flush()
        return final
