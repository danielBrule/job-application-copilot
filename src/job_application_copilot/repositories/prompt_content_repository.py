"""Session-scoped persistence operations for prompt text."""

from sqlalchemy.orm import Session

from job_application_copilot.repositories.models import PromptContent


class PromptContentRepository:
    """Read and write prompt text within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, content: PromptContent) -> PromptContent:
        """Persist prompt text and populate generated values."""

        self.session.add(content)
        self.session.flush()
        return content

    def get(self, reference_asset_id: int) -> PromptContent | None:
        """Return the content for one reference-asset version, if retained."""

        return self.session.get(PromptContent, reference_asset_id)
