# ADR-005 — Database foundation

## Status

Accepted

## Decision

- Use SQLAlchemy 2.x directly for engines, sessions and persisted models.
- Use Alembic for ordered, committed schema migrations.
- Run committed migrations automatically during local application startup.
- Use file-backed SQLite in WAL mode.
- Enable foreign-key enforcement and a five-second busy timeout on every connection.
- Create one engine per process and one session per unit of work.
- Do not share engines, pooled connections or sessions between the UI and worker processes.

## Rationale

SQLAlchemy keeps persistence models separate from Pydantic boundary models and provides explicit
session and transaction control. Alembic records the installed schema revision and supports
repeatable upgrades as the application evolves.

WAL mode reduces interference between the Streamlit reader and future background worker writer.
SQLite remains appropriate for the local, single-user application, provided transactions remain
short and only one writer operates at a time.

## Consequences

- Every schema change requires a reviewed Alembic revision.
- Application startup stops if migration or database health validation fails.
- Active SQLite backups must account for the database, WAL and shared-memory files together.
- Domain tables remain owned by their individual implementation tickets.
