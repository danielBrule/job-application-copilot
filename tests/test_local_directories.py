"""Tests for private local directory management."""

from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.services.local_directories import (
    LocalDirectoryError,
    ensure_local_directories,
)


def settings_under(data_dir: Path) -> AppSettings:
    """Build settings isolated beneath a test-owned data directory."""

    return AppSettings(_env_file=None, data_dir=data_dir)


def test_creates_required_directories_idempotently(tmp_path: Path) -> None:
    settings = settings_under(tmp_path / "private")

    first_result = ensure_local_directories(settings)
    second_result = ensure_local_directories(settings)

    assert first_result == second_result
    assert all(path.is_dir() for path in first_result)
    assert first_result == (
        settings.database_path.parent,
        settings.cv_folder,
        settings.logs_folder,
        settings.document_a_folder,
        settings.document_b_folder,
        settings.templates_folder,
        settings.french_examples_folder,
        settings.assessment_prompts_folder,
        settings.english_generation_prompts_folder,
        settings.french_generation_prompts_folder,
    )


def test_creates_only_directories_not_private_files(tmp_path: Path) -> None:
    settings = settings_under(tmp_path / "private")

    ensure_local_directories(settings)

    assert not settings.database_path.exists()
    assert not any(settings.logs_folder.iterdir())
    assert not any(settings.cv_folder.iterdir())
    assert not any(settings.french_examples_folder.iterdir())
    assert not any(settings.assessment_prompts_folder.iterdir())
    assert not any(settings.english_generation_prompts_folder.iterdir())
    assert not any(settings.french_generation_prompts_folder.iterdir())


def test_supports_specific_path_overrides(tmp_path: Path) -> None:
    settings = AppSettings(
        _env_file=None,
        data_dir=tmp_path / "unused",
        database_path=tmp_path / "database-override" / "copilot.db",
        cv_folder=tmp_path / "cv-override",
        logs_folder=tmp_path / "logs-override",
        reference_folder=tmp_path / "reference-override",
    )

    directories = ensure_local_directories(settings)

    assert all(path.is_dir() for path in directories)
    assert not settings.data_dir.exists()


def test_rejects_file_where_directory_is_required(tmp_path: Path) -> None:
    settings = settings_under(tmp_path / "private")
    settings.cv_folder.parent.mkdir(parents=True)
    settings.cv_folder.write_text("not a directory", encoding="utf-8")

    with pytest.raises(LocalDirectoryError) as captured:
        ensure_local_directories(settings)

    assert captured.value.path == settings.cv_folder
    assert str(settings.cv_folder) in str(captured.value)
    assert "Cannot prepare private directory" in str(captured.value)
