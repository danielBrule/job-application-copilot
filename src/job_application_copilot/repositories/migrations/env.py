"""Alembic runtime environment for the local SQLite database."""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from job_application_copilot.config import load_settings
from job_application_copilot.repositories.database import (
    create_database,
    create_database_url,
)
from job_application_copilot.repositories.models import Job
from job_application_copilot.services.local_directories import ensure_local_directories

target_metadata = Job.metadata


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
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
