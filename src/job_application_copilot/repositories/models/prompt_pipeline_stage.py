"""Private persisted outputs for ordered prompt-pipeline stages."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.domain.llm_call import LlmCallStatus
from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import enum_values, utc_now


class PromptPipelineStage(Base):
    """The latest durable result for one private stage of one logical task."""

    __tablename__ = "prompt_pipeline_stages"
    __table_args__ = (
        CheckConstraint("stage_position > 0", name="ck_prompt_pipeline_stages_position_positive"),
        CheckConstraint(
            "(status = 'SUCCEEDED' AND output_text IS NOT NULL) OR "
            "(status = 'FAILED' AND output_text IS NULL)",
            name="ck_prompt_pipeline_stages_output_matches_status",
        ),
        UniqueConstraint(
            "task_id", "stage_position", name="uq_prompt_pipeline_stages_task_position"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("background_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_position: Mapped[int] = mapped_column(Integer, nullable=False)
    pipeline_step: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[LlmCallStatus] = mapped_column(
        Enum(
            LlmCallStatus,
            name="prompt_pipeline_stage_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    input_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(String(512))
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
