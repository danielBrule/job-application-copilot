"""Database migration, health, and status bootstrap."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.config import load_settings
from job_application_copilot.observability import get_logger, log_event
from job_application_copilot.repositories import Database, DatabaseHealth, create_database
from job_application_copilot.services.local_directories import ensure_local_directories

logger = get_logger(__name__)
MIGRATIONS_DIRECTORY = (Path(__file__).parents[1] / "repositories" / "migrations").resolve()


class DatabaseMigrationError(RuntimeError):
    """Raised when the database cannot be migrated to the application head."""


class DatabaseHealthError(RuntimeError):
    """Raised when the migrated database fails its health checks."""


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    """Migration and health state observed during initialization."""

    database_path: Path
    previous_revision: str | None
    current_revision: str
    target_revision: str
    health: DatabaseHealth

    @property
    def migration_was_applied(self) -> bool:
        return self.previous_revision != self.current_revision


def initialize_database(database_path: Path) -> DatabaseStatus:
    """Migrate a database to head, verify health, and release connections."""

    database = create_database(database_path)
    try:
        config = _migration_config()
        previous_revision = _current_revision(database)
        target_revision = _target_revision(config)
        _validate_revision_compatibility(config, previous_revision, target_revision)
        if previous_revision != target_revision:
            log_event(
                logger,
                logging.INFO,
                "database_migration_started",
                current_revision=previous_revision,
                target_revision=target_revision,
            )
            try:
                with database.engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
            except Exception as error:
                raise DatabaseMigrationError(
                    f"Cannot migrate database '{database_path}' to "
                    f"revision '{target_revision}': {error}"
                ) from error
        else:
            log_event(
                logger,
                logging.INFO,
                "database_migration_not_required",
                current_revision=previous_revision,
                target_revision=target_revision,
            )

        current_revision = _current_revision(database)
        if current_revision != target_revision:
            raise DatabaseMigrationError(
                f"Database '{database_path}' is at revision "
                f"'{current_revision}', expected '{target_revision}'."
            )

        try:
            health = database.health_check()
        except SQLAlchemyError as error:
            raise DatabaseHealthError(
                f"Database health check failed for '{database_path}': {error}"
            ) from error

        if (
            health.journal_mode.lower() != "wal"
            or not health.foreign_keys_enabled
            or health.busy_timeout_ms != 5_000
        ):
            raise DatabaseHealthError(
                f"Database health check failed for '{database_path}': "
                f"journal_mode={health.journal_mode}, "
                f"foreign_keys={health.foreign_keys_enabled}, "
                f"busy_timeout_ms={health.busy_timeout_ms}."
            )

        log_event(
            logger,
            logging.INFO,
            "database_ready",
            current_revision=current_revision,
            journal_mode=health.journal_mode,
        )
        return DatabaseStatus(
            database_path=database_path,
            previous_revision=previous_revision,
            current_revision=current_revision,
            target_revision=target_revision,
            health=health,
        )
    finally:
        database.dispose()


def _migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
    return config


def _target_revision(config: Config) -> str:
    revision = ScriptDirectory.from_config(config).get_current_head()
    if revision is None:
        raise DatabaseMigrationError("The application has no migration head.")
    return revision


def _validate_revision_compatibility(
    config: Config,
    current_revision: str | None,
    target_revision: str,
) -> None:
    if current_revision is None or current_revision == target_revision:
        return

    script = ScriptDirectory.from_config(config)
    try:
        target_lineage = _revision_lineage(script, target_revision)
        current_lineage = _revision_lineage(script, current_revision)
    except RevisionError as error:
        raise DatabaseMigrationError(
            f"Database revision '{current_revision}' is unknown to this application. "
            "The database may have been created by a newer application version."
        ) from error

    if current_revision in target_lineage:
        return
    if target_revision in current_lineage:
        raise DatabaseMigrationError(
            f"Database revision '{current_revision}' is newer than this application's "
            f"target revision '{target_revision}'. Upgrade the application before using "
            "this database."
        )
    raise DatabaseMigrationError(
        f"Database revision '{current_revision}' is not an ancestor of this "
        f"application's target revision '{target_revision}'. The migration histories "
        "have diverged."
    )


def _revision_lineage(script: ScriptDirectory, revision: str) -> set[str]:
    return {
        migration.revision for migration in script.revision_map.iterate_revisions(revision, "base")
    }


def _current_revision(database: Database) -> str | None:
    try:
        with database.engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    except SQLAlchemyError as error:
        raise DatabaseHealthError(
            f"Cannot inspect database revision for '{database.database_path}': {error}"
        ) from error


def main() -> None:
    """Initialize the configured database and display its final status."""

    settings = load_settings()
    ensure_local_directories(settings)
    status = initialize_database(settings.database_path)
    previous = status.previous_revision or "none"
    migration_status = "upgraded" if status.migration_was_applied else "up to date"
    print(f"Database: {status.database_path}")
    print(f"Previous revision: {previous}")
    print(f"Current revision: {status.current_revision}")
    print(f"Target revision: {status.target_revision}")
    print(f"Migration status: {migration_status}")
    print("Health check: passed")
    print(f"Journal mode: {status.health.journal_mode.upper()}")
    print(f"Foreign keys: {'enabled' if status.health.foreign_keys_enabled else 'disabled'}")
    print(f"Busy timeout: {status.health.busy_timeout_ms} ms")


if __name__ == "__main__":
    main()
