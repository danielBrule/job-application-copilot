"""Private persisted structured output from CV-generation stage two."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import utc_now


class CvGenerationDraft(Base):
    """One validated first CV draft retained for one logical CV-generation task."""

    __tablename__ = "cv_generation_drafts"
    __table_args__ = (UniqueConstraint("task_id", name="uq_cv_generation_drafts_task"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("background_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_a_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_b_version: Mapped[int] = mapped_column(Integer, nullable=False)
    routing_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
