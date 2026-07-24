"""Integration tests for SQLAlchemy SQLite infrastructure."""

from pathlib import Path

import pytest
from sqlalchemy import text

from job_application_copilot.repositories import create_database
from job_application_copilot.repositories.database import (
    _configure_sqlite_connection,
)


def test_configures_file_database_health_pragmas(tmp_path: Path) -> None:
    database_path = tmp_path / "database" / "copilot.db"
    database_path.parent.mkdir()
    database = create_database(database_path)

    try:
        health = database.health_check()

        assert database_path.exists()
        assert health.journal_mode.lower() == "wal"
        assert health.foreign_keys_enabled
        assert health.busy_timeout_ms == 5_000
        assert database.engine.url.database == str(database_path.resolve())
    finally:
        database.dispose()


def test_session_commits_on_success_and_rolls_back_on_error(tmp_path: Path) -> None:
    database_path = tmp_path / "copilot.db"
    database = create_database(database_path)

    try:
        with database.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE test_values (id INTEGER PRIMARY KEY, value TEXT)")
            )

        with database.session() as session:
            session.execute(
                text("INSERT INTO test_values (value) VALUES (:value)"),
                {"value": "committed"},
            )

        with pytest.raises(RuntimeError, match="force rollback"):
            with database.session() as session:
                session.execute(
                    text("INSERT INTO test_values (value) VALUES (:value)"),
                    {"value": "rolled back"},
                )
                raise RuntimeError("force rollback")

        with database.engine.connect() as connection:
            values = list(
                connection.execute(text("SELECT value FROM test_values ORDER BY id")).scalars()
            )

        assert values == ["committed"]
    finally:
        database.dispose()


def test_each_unit_of_work_receives_a_distinct_session(tmp_path: Path) -> None:
    database = create_database(tmp_path / "copilot.db")

    try:
        with database.session() as first_session:
            first_identity = id(first_session)
        with database.session() as second_session:
            second_identity = id(second_session)

        assert first_identity != second_identity
    finally:
        database.dispose()


def test_rejects_non_sqlite_connection() -> None:
    with pytest.raises(TypeError, match="received object"):
        _configure_sqlite_connection(object(), object())
