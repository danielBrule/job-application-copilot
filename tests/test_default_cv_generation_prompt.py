"""Tests for one-time installation of default English generation prompts."""

from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.services import DefaultCvGenerationPromptService, PromptService
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.local_directories import ensure_local_directories


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Database, AppSettings]:
    settings = AppSettings(data_dir=tmp_path / "data", _env_file=None)
    ensure_local_directories(settings)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        yield database, settings
    finally:
        database.dispose()


def test_installs_private_version_one_without_overwriting_user_versions(
    setup: tuple[Database, AppSettings],
) -> None:
    database, settings = setup
    service = DefaultCvGenerationPromptService(database, settings)

    assert service.ensure()
    assert not service.ensure()
    active = PromptService(database).get_active_version("cv-generation-en-stage-1")
    assert active is not None
    assert active.version == 1
    assert active.file_path is None
    stage_two = PromptService(database).get_active_version("cv-generation-en-stage-2")
    stage_three = PromptService(database).get_active_version("cv-generation-en-stage-3")
    assert stage_two is not None
    assert stage_two.version == 1
    assert stage_two.file_path is None
    assert stage_three.file_path is None
