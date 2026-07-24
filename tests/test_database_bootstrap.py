"""Integration tests for Alembic migration and database bootstrap."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from sqlalchemy import inspect

from job_application_copilot.repositories import create_database
from job_application_copilot.services import database_bootstrap
from job_application_copilot.services.database_bootstrap import (
    DatabaseHealthError,
    DatabaseMigrationError,
    _validate_revision_compatibility,
    initialize_database,
)

HEAD_REVISION = "0002_create_jobs_table"


def test_creates_and_repeatedly_migrates_foundation_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "database" / "copilot.db"
    database_path.parent.mkdir()
    actual_upgrade = database_bootstrap.command.upgrade
    upgrade_calls = 0

    def record_upgrade(config: Config, revision: str) -> None:
        nonlocal upgrade_calls
        upgrade_calls += 1
        actual_upgrade(config, revision)

    monkeypatch.setattr(database_bootstrap.command, "upgrade", record_upgrade)

    first_status = initialize_database(database_path)
    second_status = initialize_database(database_path)

    assert upgrade_calls == 1
    assert database_path.exists()
    assert first_status.previous_revision is None
    assert first_status.migration_was_applied
    assert first_status.current_revision == HEAD_REVISION
    assert first_status.target_revision == HEAD_REVISION
    assert second_status.previous_revision == HEAD_REVISION
    assert not second_status.migration_was_applied
    assert second_status.current_revision == HEAD_REVISION
    assert second_status.health.journal_mode.lower() == "wal"
    assert second_status.health.foreign_keys_enabled
    assert second_status.health.busy_timeout_ms == 5_000


def test_migrations_create_revision_metadata_and_jobs_table(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)

    try:
        assert inspect(database.engine).get_table_names() == ["alembic_version", "jobs"]
    finally:
        database.dispose()


def test_reports_unusable_database_destination(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("blocked", encoding="utf-8")

    with pytest.raises((DatabaseHealthError, DatabaseMigrationError)) as captured:
        initialize_database(parent_file / "copilot.db")

    assert "copilot.db" in str(captured.value)


class FakeRevisionMap:
    def __init__(self, lineages: dict[str, list[str]]) -> None:
        self.lineages = lineages

    def iterate_revisions(
        self,
        revision: str,
        base: str,
    ) -> list[SimpleNamespace]:
        del base
        try:
            return [SimpleNamespace(revision=item) for item in self.lineages[revision]]
        except KeyError as error:
            raise ResolutionError(
                f"Unknown revision {revision}",
                revision,
            ) from error


class FakeScriptDirectory:
    def __init__(self, lineages: dict[str, list[str]]) -> None:
        self.revision_map = FakeRevisionMap(lineages)


def test_accepts_database_behind_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = FakeScriptDirectory(
        {
            "0002": ["0002", "0001"],
            "0001": ["0001"],
        }
    )
    monkeypatch.setattr(
        ScriptDirectory,
        "from_config",
        lambda config: cast(ScriptDirectory, script),
    )

    _validate_revision_compatibility(Config(), "0001", "0002")


def test_rejects_database_newer_than_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = FakeScriptDirectory(
        {
            "0002": ["0002", "0001"],
            "0001": ["0001"],
        }
    )
    monkeypatch.setattr(
        ScriptDirectory,
        "from_config",
        lambda config: cast(ScriptDirectory, script),
    )

    with pytest.raises(DatabaseMigrationError, match="newer than") as captured:
        _validate_revision_compatibility(Config(), "0002", "0001")

    assert "Upgrade the application" in str(captured.value)


def test_rejects_divergent_database_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = FakeScriptDirectory(
        {
            "branch_a": ["branch_a", "base_revision"],
            "branch_b": ["branch_b", "base_revision"],
        }
    )
    monkeypatch.setattr(
        ScriptDirectory,
        "from_config",
        lambda config: cast(ScriptDirectory, script),
    )

    with pytest.raises(DatabaseMigrationError, match="diverged"):
        _validate_revision_compatibility(Config(), "branch_a", "branch_b")


def test_rejects_revision_unknown_to_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = FakeScriptDirectory({"0001": ["0001"]})
    monkeypatch.setattr(
        ScriptDirectory,
        "from_config",
        lambda config: cast(ScriptDirectory, script),
    )

    with pytest.raises(DatabaseMigrationError, match="unknown") as captured:
        _validate_revision_compatibility(Config(), "future_revision", "0001")

    assert "newer application version" in str(captured.value)
