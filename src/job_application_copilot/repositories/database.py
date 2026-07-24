"""SQLAlchemy engine, sessions, and SQLite health checks."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import URL, Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

SQLITE_BUSY_TIMEOUT_MS = 5_000


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    """Observed SQLite connection configuration."""

    journal_mode: str
    foreign_keys_enabled: bool
    busy_timeout_ms: int


@dataclass(slots=True)
class Database:
    """Process-local SQLAlchemy engine and session factory."""

    database_path: Path
    engine: Engine
    session_factory: sessionmaker[Session]

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Provide a transaction that commits or rolls back and always closes."""

        with self.session_factory() as session:
            with session.begin():
                yield session

    def health_check(self) -> DatabaseHealth:
        """Verify connectivity and required SQLite pragmas."""

        with self.engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
            journal_mode = str(connection.exec_driver_sql("PRAGMA journal_mode").scalar_one())
            foreign_keys = int(connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one())
            busy_timeout = int(connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one())

        return DatabaseHealth(
            journal_mode=journal_mode,
            foreign_keys_enabled=foreign_keys == 1,
            busy_timeout_ms=busy_timeout,
        )

    def dispose(self) -> None:
        """Close pooled database connections owned by this process."""

        self.engine.dispose()


def create_database(database_path: Path) -> Database:
    """Create a process-local SQLAlchemy database facade."""

    absolute_path = database_path.resolve()
    url = create_database_url(absolute_path)
    engine = create_engine(url, pool_pre_ping=True)
    event.listen(engine, "connect", _configure_sqlite_connection)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return Database(
        database_path=absolute_path,
        engine=engine,
        session_factory=factory,
    )


def create_database_url(database_path: Path) -> URL:
    """Build a Windows-safe SQLAlchemy URL for a SQLite database file."""

    return URL.create("sqlite+pysqlite", database=str(database_path.resolve()))


def _configure_sqlite_connection(
    dbapi_connection: object,
    connection_record: object,
) -> None:
    del connection_record
    if not isinstance(dbapi_connection, SQLiteConnection):
        raise TypeError(
            "Expected a sqlite3.Connection while configuring the SQLite engine, "
            f"received {type(dbapi_connection).__name__}."
        )

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()
