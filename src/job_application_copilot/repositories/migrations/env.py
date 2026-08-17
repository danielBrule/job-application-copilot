"""Alembic runtime environment for the local SQLite database."""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from job_application_copilot.config import load_settings
from job_application_copilot.repositories import models
from job_application_copilot.repositories.database import (
    create_database,
    create_database_url,
)
from job_application_copilot.services.local_directories import ensure_local_directories

target_metadata = models.ReferenceAsset.metadata


def run_migrations_offline() -> None:
    """Render migrations without creating a database connection."""

    settings = load_settings()
    context.configure(
        url=create_database_url(settings.database_path),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with an injected or locally configured connection."""

    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        _run_with_connection(supplied_connection)
    else:
        settings = load_settings()
        ensure_local_directories(settings)
        database = create_database(settings.database_path)
        try:
            with database.engine.connect() as connection:
                _run_with_connection(connection)
        finally:
            database.dispose()


def _run_with_connection(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        _run_sqlite_migrations(connection)
        return

    _run_migrations(connection)


def _run_sqlite_migrations(connection: Connection) -> None:
    """Run SQLite batch migrations without cascading rows during table rebuilds."""

    if connection.in_transaction():
        raise RuntimeError(
            "SQLite migrations require an idle connection so foreign-key enforcement can "
            "be suspended safely."
        )

    foreign_keys_were_enabled = _sqlite_foreign_keys_enabled(connection)
    if foreign_keys_were_enabled:
        _set_sqlite_foreign_keys(connection, enabled=False)

    try:
        _run_migrations(connection)
        if connection.in_transaction():
            connection.commit()
        _verify_sqlite_foreign_keys(connection)
    finally:
        if connection.in_transaction():
            connection.rollback()
        if foreign_keys_were_enabled:
            _set_sqlite_foreign_keys(connection, enabled=True)


def _run_migrations(connection: Connection) -> None:
    """Configure Alembic and run migrations over one prepared connection."""

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _sqlite_foreign_keys_enabled(connection: Connection) -> bool:
    """Read SQLite foreign-key enforcement without retaining an open transaction."""

    enabled = int(connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()) == 1
    connection.commit()
    return enabled


def _set_sqlite_foreign_keys(connection: Connection, *, enabled: bool) -> None:
    """Set SQLite foreign-key enforcement while the connection is idle."""

    setting = "ON" if enabled else "OFF"
    connection.exec_driver_sql(f"PRAGMA foreign_keys={setting}")
    connection.commit()
    observed = _sqlite_foreign_keys_enabled(connection)
    if observed != enabled:
        raise RuntimeError(
            f"Cannot set SQLite foreign-key enforcement to {setting} during migration."
        )


def _verify_sqlite_foreign_keys(connection: Connection) -> None:
    """Reject a completed SQLite migration containing orphaned relationships."""

    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    connection.commit()
    if violations:
        raise RuntimeError("Database migration created invalid foreign-key relationships.")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
