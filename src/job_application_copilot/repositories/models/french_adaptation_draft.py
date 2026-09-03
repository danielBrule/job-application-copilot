"""Private persisted structured output from French adaptation stage one."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.repositories.base import Base
from job_application_copilot.repositories.models.common import utc_now


class FrenchAdaptationDraft(Base):
    """One validated French draft retained for one logical CV-generation task."""

    __tablename__ = "french_adaptation_drafts"
    __table_args__ = (UniqueConstraint("task_id", name="uq_french_adaptation_drafts_task"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("background_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    document_a_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_b_version: Mapped[int] = mapped_column(Integer, nullable=False)
    english_final_prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    french_prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    english_template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    french_template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    french_reference_versions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.current_timestamp()
    )
