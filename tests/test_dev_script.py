from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
DEV_SCRIPT = PROJECT_ROOT / "dev.ps1"
POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(
    POWERSHELL is None,
    reason="T1.1A supports Windows PowerShell only.",
)


@pytest.fixture
def workspace_tmp_path() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="job-copilot-dev-script-") as directory:
        yield Path(directory)


def run_dev_script(
    *arguments: str,
    cwd: Path = PROJECT_ROOT,
    script: Path = DEV_SCRIPT,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            POWERSHELL or "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *arguments,
        ],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


def test_no_target_displays_help() -> None:
    result = run_dev_script()

    assert result.returncode == 0
    assert "Job Application Copilot developer commands" in result.stdout
    assert r".\dev.ps1 test" in result.stdout


def test_explicit_help_displays_supported_targets() -> None:
    result = run_dev_script("help")

    assert result.returncode == 0
    for target in (
        "env",
        "activate",
        "directories",
        "database",
        "database-sql",
        "test",
        "lint",
        "ui",
    ):
        assert target in result.stdout


def test_unknown_target_fails_clearly() -> None:
    result = run_dev_script("unknown")

    assert result.returncode != 0
    assert "Unknown target 'unknown'." in combined_output(result)


def test_missing_environment_has_actionable_error(workspace_tmp_path: Path) -> None:
    isolated_script = workspace_tmp_path / "dev.ps1"
    shutil.copy2(DEV_SCRIPT, isolated_script)

    result = run_dev_script(
        "test",
        cwd=workspace_tmp_path,
        script=isolated_script,
    )

    assert result.returncode != 0
    assert r"Run '.\dev.ps1 env' first." in combined_output(result)


def test_missing_poetry_has_actionable_error(workspace_tmp_path: Path) -> None:
    isolated_script = workspace_tmp_path / "dev.ps1"
    shutil.copy2(DEV_SCRIPT, isolated_script)
    environment = os.environ.copy()
    environment["APPDATA"] = ""
    environment["PATH"] = str(Path(os.environ["WINDIR"]) / "System32")

    result = run_dev_script(
        "env",
        cwd=workspace_tmp_path,
        script=isolated_script,
        environment=environment,
    )

    assert result.returncode != 0
    assert "Poetry was not found." in combined_output(result)


def test_activation_requires_dot_sourcing() -> None:
    result = run_dev_script("activate")

    assert result.returncode != 0
    assert r"Run: . .\dev.ps1 activate" in combined_output(result)


def test_directories_target_is_idempotent(
    workspace_tmp_path: Path,
) -> None:
    data_dir = workspace_tmp_path / "private-data"
    environment = os.environ.copy()
    environment["JAC_DATA_DIR"] = str(data_dir)

    first_result = run_dev_script("directories", environment=environment)
    second_result = run_dev_script("directories", environment=environment)

    assert first_result.returncode == 0, combined_output(first_result)
    assert second_result.returncode == 0, combined_output(second_result)
    assert "Private directories are ready:" in first_result.stdout
    assert (data_dir / "database").is_dir()
    assert (data_dir / "cvs").is_dir()
    assert (data_dir / "logs").is_dir()
    assert (data_dir / "reference" / "document_a").is_dir()
    assert (data_dir / "reference" / "document_b").is_dir()
    assert (data_dir / "reference" / "templates").is_dir()
    assert (data_dir / "reference" / "examples").is_dir()
    assert (data_dir / "reference" / "prompts" / "assessment").is_dir()
    assert (data_dir / "reference" / "prompts" / "generation" / "english").is_dir()
    assert (data_dir / "reference" / "prompts" / "generation" / "french").is_dir()


def test_directories_target_reports_conflicting_file(
    workspace_tmp_path: Path,
) -> None:
    data_dir = workspace_tmp_path / "private-data"
    data_dir.mkdir()
    (data_dir / "cvs").write_text("not a directory", encoding="utf-8")
    environment = os.environ.copy()
    environment["JAC_DATA_DIR"] = str(data_dir)

    result = run_dev_script("directories", environment=environment)

    assert result.returncode != 0
    assert "Cannot prepare private directory" in combined_output(result)
    assert str(data_dir / "cvs") in combined_output(result)


def test_database_target_is_idempotent(
    workspace_tmp_path: Path,
) -> None:
    data_dir = workspace_tmp_path / "private-data"
    environment = os.environ.copy()
    environment["JAC_DATA_DIR"] = str(data_dir)

    first_result = run_dev_script("database", environment=environment)
    second_result = run_dev_script("database", environment=environment)

    assert first_result.returncode == 0, combined_output(first_result)
    assert second_result.returncode == 0, combined_output(second_result)
    assert "Previous revision: none" in first_result.stdout
    assert "Migration status: upgraded" in first_result.stdout
    assert "Migration status: up to date" in second_result.stdout
    assert "Current revision: 0001_database_foundation" in second_result.stdout
    assert "Target revision: 0001_database_foundation" in second_result.stdout
    assert "Health check: passed" in second_result.stdout
    assert "Journal mode: WAL" in second_result.stdout
    assert "Foreign keys: enabled" in second_result.stdout
    assert "Busy timeout: 5000 ms" in second_result.stdout
    assert (data_dir / "database" / "job_application_copilot.db").is_file()


def test_database_sql_target_is_offline(
    workspace_tmp_path: Path,
) -> None:
    data_dir = workspace_tmp_path / "private-data"
    environment = os.environ.copy()
    environment["JAC_DATA_DIR"] = str(data_dir)

    result = run_dev_script("database-sql", environment=environment)

    assert result.returncode == 0, combined_output(result)
    assert "CREATE TABLE alembic_version" in result.stdout
    assert "0001_database_foundation" in result.stdout
    assert not data_dir.exists()


def test_dot_sourced_activation_sets_virtual_environment(
    workspace_tmp_path: Path,
) -> None:
    escaped_script = str(DEV_SCRIPT).replace("'", "''")
    command = f". '{escaped_script}' activate; Write-Output \"VIRTUAL_ENV=$env:VIRTUAL_ENV\""

    result = subprocess.run(
        [
            POWERSHELL or "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=workspace_tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert f"VIRTUAL_ENV={PROJECT_ROOT / '.venv'}" in result.stdout


def test_lint_target_runs_from_outside_project(
    workspace_tmp_path: Path,
) -> None:
    result = run_dev_script("lint", cwd=workspace_tmp_path)

    assert result.returncode == 0, combined_output(result)
    assert "All checks passed!" in result.stdout
