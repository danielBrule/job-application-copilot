"""SQLAlchemy persistence model for prompt text stored in SQLite."""

from sqlalchemy import CheckConstraint, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from job_application_copilot.repositories.base import Base


class PromptContent(Base):
    """The immutable text payload for one prompt reference-asset version."""

    __tablename__ = "prompt_contents"
    __table_args__ = (
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_prompt_contents_content_not_blank",
        ),
    )

    reference_asset_id: Mapped[int] = mapped_column(
        ForeignKey("reference_assets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
