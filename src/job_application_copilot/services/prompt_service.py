"""Data-driven prompt definitions, completeness, and private text versions."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    CreatePromptDefinition,
    PromptCompleteness,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.models import PromptDefinition, ReferenceAsset
from job_application_copilot.repositories.prompt_definition_repository import (
    PromptDefinitionRepository,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFileExistsError,
    ImmutableFilePathError,
    ImmutableFileWriteError,
    relative_path_within,
    remove_created_file,
    resolve_path_within,
    sha256_file_hash,
    write_bytes_exclusively,
)


class DuplicatePromptDefinitionError(ValueError):
    """Raised when a definition key or group position is already occupied."""


class DuplicatePromptContentError(ValueError):
    """Raised when identical text already exists for a logical prompt."""

    def __init__(self, asset_key: str, existing_version: int) -> None:
        self.asset_key = asset_key
        self.existing_version = existing_version
        super().__init__(
            f"Prompt '{asset_key}' already has identical content in version {existing_version}."
        )


class PromptStorageError(RuntimeError):
    """Raised when private prompt text cannot be stored or read safely."""


class PromptActivationError(ValueError):
    """Raised when a prompt version cannot become active."""


class PromptService:
    """Manage prompt definitions and immutable active text versions."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings

    def create_definition(self, command: CreatePromptDefinition) -> PromptDefinition:
        """Create a new prompt definition without hard-coded groups or languages."""

        with self.database.session() as session:
            repository = PromptDefinitionRepository(session)
            if repository.get(command.asset_key) is not None:
                raise DuplicatePromptDefinitionError(
                    f"Prompt definition '{command.asset_key}' already exists."
                )
            if ReferenceAssetRepository(session).list_versions(command.asset_key):
                raise DuplicatePromptDefinitionError(
                    f"Reference asset key '{command.asset_key}' is already used by stored versions."
                )
            occupied = repository.get_at_position(command.pipeline_group, command.position)
            if occupied is not None:
                raise DuplicatePromptDefinitionError(
                    f"Pipeline group '{command.pipeline_group}' position "
                    f"{command.position} is already used by '{occupied.asset_key}'."
                )
            return repository.add(
                PromptDefinition(
                    asset_key=command.asset_key,
                    name=command.name,
                    pipeline_group=command.pipeline_group,
                    language_code=command.language_code,
                    position=command.position,
                    is_enabled=command.is_enabled,
                )
            )

    def list_definitions(self, *, enabled_only: bool = False) -> list[PromptDefinition]:
        """Return prompt definitions in deterministic group and stage order."""

        with self.database.session() as session:
            return PromptDefinitionRepository(session).list(enabled_only=enabled_only)

    def set_enabled(self, asset_key: str, enabled: bool) -> PromptDefinition:
        """Change whether a retained definition counts as required."""

        with self.database.session() as session:
            definition = PromptDefinitionRepository(session).require(asset_key)
            definition.is_enabled = enabled
            session.flush()
            return definition

    def completeness(self) -> tuple[PromptCompleteness, ...]:
        """Report required, ready, and missing prompt keys by pipeline group."""

        with self.database.session() as session:
            definitions = PromptDefinitionRepository(session).list(enabled_only=True)
            ready_keys = {
                asset.asset_key
                for asset in ReferenceAssetRepository(session).list_active_ready_prompts()
            }

        groups: OrderedDict[str, list[PromptDefinition]] = OrderedDict()
        for definition in definitions:
            groups.setdefault(definition.pipeline_group, []).append(definition)

        return tuple(
            PromptCompleteness(
                pipeline_group=pipeline_group,
                language_code=self._common_language(group_definitions),
                required_count=len(group_definitions),
                ready_count=sum(
                    definition.asset_key in ready_keys for definition in group_definitions
                ),
                missing_asset_keys=tuple(
                    definition.asset_key
                    for definition in group_definitions
                    if definition.asset_key not in ready_keys
                ),
            )
            for pipeline_group, group_definitions in groups.items()
        )

    def save_text(self, asset_key: str, text: str) -> ReferenceAsset:
        """Save nonblank UTF-8 text as a new READY and active immutable version."""

        if not text.strip():
            raise ValueError("Prompt text must not be blank.")

        content = text.encode("utf-8")
        file_hash = sha256_file_hash(content)
        stored_path: Path | None = None
        file_created = False

        try:
            with self.database.session() as session:
                definition = PromptDefinitionRepository(session).require(asset_key)
                repository = ReferenceAssetRepository(session)
                duplicate = repository.find_by_hash(asset_key, file_hash)
                if duplicate is not None:
                    raise DuplicatePromptContentError(asset_key, duplicate.version)

                version = repository.next_version(asset_key)
                destination = self._prompt_folder(definition.pipeline_group)
                destination.mkdir(parents=True, exist_ok=True)
                stored_path = destination / f"{asset_key}-v{version:04d}.txt"
                self._store_prompt_file(stored_path, content)
                file_created = True

                current = repository.get_active(asset_key)
                if current is not None:
                    current.is_active = False
                    session.flush()

                return repository.add(
                    ReferenceAsset(
                        asset_key=asset_key,
                        asset_type=ReferenceAssetType.PROMPT,
                        name=definition.name,
                        language_code=definition.language_code,
                        version=version,
                        file_path=self._relative_file_path(stored_path),
                        file_hash=file_hash,
                        is_active=True,
                        processing_status=ReferenceAssetProcessingStatus.READY,
                    )
                )
        except Exception:
            remove_created_file(stored_path, created=file_created)
            raise

    def get_active_version(self, asset_key: str) -> ReferenceAsset | None:
        """Return the active prompt version, if one exists."""

        with self.database.session() as session:
            PromptDefinitionRepository(session).require(asset_key)
            return ReferenceAssetRepository(session).get_active(asset_key)

    def get_active_text(self, asset_key: str) -> str | None:
        """Read the active private prompt text, or None when it is missing."""

        active = self.get_active_version(asset_key)
        if active is None:
            return None
        return self._read_text(active)

    def list_versions(self, asset_key: str) -> list[ReferenceAsset]:
        """Return retained prompt versions, newest first."""

        with self.database.session() as session:
            PromptDefinitionRepository(session).require(asset_key)
            return ReferenceAssetRepository(session).list_versions(asset_key)

    def activate_version(self, asset_key: str, version: int) -> ReferenceAsset:
        """Activate a retained READY prompt version without deleting newer versions."""

        with self.database.session() as session:
            PromptDefinitionRepository(session).require(asset_key)
            repository = ReferenceAssetRepository(session)
            target = repository.require_version(asset_key, version)
            if target.asset_type is not ReferenceAssetType.PROMPT:
                raise PromptActivationError(
                    f"Reference asset '{asset_key}' version {version} is not a prompt."
                )
            if target.processing_status is not ReferenceAssetProcessingStatus.READY:
                raise PromptActivationError(f"Prompt '{asset_key}' version {version} is not READY.")
            if target.is_active:
                return target

            current = repository.get_active(asset_key)
            if current is not None:
                current.is_active = False
                session.flush()
            target.is_active = True
            session.flush()
            return target

    @staticmethod
    def _common_language(definitions: list[PromptDefinition]) -> str | None:
        languages = {definition.language_code for definition in definitions}
        return languages.pop() if len(languages) == 1 else None

    def _prompt_folder(self, pipeline_group: str) -> Path:
        destination = self.settings.prompts_folder.joinpath(*pipeline_group.split("/"))
        self._ensure_within_prompts_folder(destination)
        return destination

    def _relative_file_path(self, stored_path: Path) -> str:
        try:
            return relative_path_within(self.settings.reference_folder, stored_path)
        except ImmutableFilePathError as error:
            raise PromptStorageError(
                "Prompt folders must be located under the configured reference folder."
            ) from error

    def _read_text(self, asset: ReferenceAsset) -> str:
        path = self.settings.reference_folder / asset.file_path
        self._ensure_within_prompts_folder(path)
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise PromptStorageError(
                f"Cannot read prompt '{asset.asset_key}' version {asset.version}: {error}"
            ) from error

    def _ensure_within_prompts_folder(self, path: Path) -> None:
        try:
            resolve_path_within(self.settings.prompts_folder, path)
        except ImmutableFilePathError as error:
            raise PromptStorageError(
                f"Prompt path is outside the configured prompt folder: {path}"
            ) from error

    @staticmethod
    def _store_prompt_file(path: Path, content: bytes) -> None:
        try:
            write_bytes_exclusively(path, content)
        except ImmutableFileExistsError as error:
            raise PromptStorageError(
                f"Prompt version path already exists and will not be overwritten: {path}"
            ) from error
        except ImmutableFileWriteError as error:
            raise PromptStorageError(
                f"Could not store prompt text at {path}: {error.__cause__}"
            ) from error
