"""Session-scoped persistence operations for prompt definitions."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.errors import ApplicationNotFoundError
from job_application_copilot.repositories.models import PromptDefinition


class PromptDefinitionNotFoundError(ApplicationNotFoundError):
    """Raised when a required prompt definition does not exist."""

    def __init__(self, asset_key: str) -> None:
        self.asset_key = asset_key
        super().__init__(f"Prompt definition '{asset_key}' does not exist.")


class PromptDefinitionRepository:
    """Read and write prompt definitions within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, definition: PromptDefinition) -> PromptDefinition:
        """Persist a prompt definition."""

        self.session.add(definition)
        self.session.flush()
        return definition

    def get(self, asset_key: str) -> PromptDefinition | None:
        """Return a prompt definition by its stable asset key."""

        return self.session.get(PromptDefinition, asset_key)

    def require(self, asset_key: str) -> PromptDefinition:
        """Return a prompt definition or raise an actionable lookup error."""

        definition = self.get(asset_key)
        if definition is None:
            raise PromptDefinitionNotFoundError(asset_key)
        return definition

    def get_at_position(
        self,
        pipeline_group: str,
        position: int,
    ) -> PromptDefinition | None:
        """Return the definition occupying a group position, if one exists."""

        return self.session.scalar(
            select(PromptDefinition).where(
                PromptDefinition.pipeline_group == pipeline_group,
                PromptDefinition.position == position,
            )
        )

    def list(self, *, enabled_only: bool = False) -> list[PromptDefinition]:
        """List definitions in deterministic group and pipeline order."""

        statement = select(PromptDefinition)
        if enabled_only:
            statement = statement.where(PromptDefinition.is_enabled.is_(True))
        statement = statement.order_by(
            PromptDefinition.pipeline_group,
            PromptDefinition.position,
            PromptDefinition.asset_key,
        )
        return list(self.session.scalars(statement))
