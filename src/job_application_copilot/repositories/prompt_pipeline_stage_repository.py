"""Persistence operations for resumable ordered prompt stages."""

import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from job_application_copilot.domain import LlmCallStatus
from job_application_copilot.errors import ApplicationValidationError
from job_application_copilot.repositories.models import PromptPipelineStage
from job_application_copilot.repositories.models.common import utc_now


class PromptPipelineStageRepository:
    """Store private stage outputs separately from privacy-safe LLM telemetry."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_task(self, task_id: int) -> list[PromptPipelineStage]:
        statement = (
            select(PromptPipelineStage)
            .where(PromptPipelineStage.task_id == task_id)
            .order_by(PromptPipelineStage.stage_position)
        )
        return list(self.session.scalars(statement))

    def get(self, task_id: int, stage_position: int) -> PromptPipelineStage | None:
        return self.session.scalar(
            select(PromptPipelineStage).where(
                PromptPipelineStage.task_id == task_id,
                PromptPipelineStage.stage_position == stage_position,
            )
        )

    def store_success(
        self,
        *,
        task_id: int,
        stage_position: int,
        pipeline_step: str,
        input_identity_hash: str,
        output_text: str,
    ) -> PromptPipelineStage:
        self._validate_identity(input_identity_hash)
        if not output_text.strip():
            raise ApplicationValidationError("A successful prompt stage requires output text.")
        stage = self.get(task_id, stage_position)
        if stage is None:
            stage = PromptPipelineStage(task_id=task_id, stage_position=stage_position)
            self.session.add(stage)
        stage.pipeline_step = pipeline_step
        stage.status = LlmCallStatus.SUCCEEDED
        stage.input_identity_hash = input_identity_hash
        stage.output_text = output_text
        stage.error_message = None
        stage.completed_at = utc_now()
        self.session.flush()
        return stage

    def store_failure(
        self,
        *,
        task_id: int,
        stage_position: int,
        pipeline_step: str,
        input_identity_hash: str,
        error_message: str,
    ) -> PromptPipelineStage:
        self._validate_identity(input_identity_hash)
        stage = self.get(task_id, stage_position)
        if stage is None:
            stage = PromptPipelineStage(task_id=task_id, stage_position=stage_position)
            self.session.add(stage)
        stage.pipeline_step = pipeline_step
        stage.status = LlmCallStatus.FAILED
        stage.input_identity_hash = input_identity_hash
        stage.output_text = None
        stage.error_message = error_message[:512]
        stage.completed_at = utc_now()
        self.session.flush()
        return stage

    def delete_from(self, *, task_id: int, stage_position: int) -> None:
        self.session.execute(
            delete(PromptPipelineStage).where(
                PromptPipelineStage.task_id == task_id,
                PromptPipelineStage.stage_position >= stage_position,
            )
        )
        self.session.flush()

    @staticmethod
    def _validate_identity(value: str) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ApplicationValidationError(
                "A prompt-stage input identity must be a lowercase SHA-256 hexadecimal digest."
            )
