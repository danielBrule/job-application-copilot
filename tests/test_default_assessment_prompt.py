"""Tests for one-time installation of the packaged assessment prompt."""

from importlib import resources
from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.services import (
    DefaultAssessmentPromptError,
    DefaultAssessmentPromptService,
    PromptService,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.default_assessment_prompt import (
    DEFAULT_ASSESSMENT_PROMPT_FILENAME,
)
from job_application_copilot.services.local_directories import ensure_local_directories


@pytest.fixture
def prompt_setup(tmp_path: Path) -> tuple[Database, AppSettings]:
    settings = AppSettings(data_dir=tmp_path / "data", _env_file=None)
    ensure_local_directories(settings)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        yield database, settings
    finally:
        database.dispose()


def test_installs_packaged_prompt_as_active_private_version_one(
    prompt_setup: tuple[Database, AppSettings],
) -> None:
    database, settings = prompt_setup

    created = DefaultAssessmentPromptService(database, settings).ensure()

    service = PromptService(database, settings)
    active = service.get_active_version("assessment")
    assert created
    assert active is not None
    assert active.version == 1
    assert active.is_active
    assert active.file_path == "prompts/assessment/assessment-v0001.txt"
    assert service.get_active_text("assessment") == _packaged_prompt_text()


def test_root_template_matches_packaged_fallback() -> None:
    root_template = Path(__file__).parents[1] / "templates" / DEFAULT_ASSESSMENT_PROMPT_FILENAME

    assert root_template.read_text(encoding="utf-8") == _packaged_prompt_text()


def test_uses_configured_template_directory_when_present(
    prompt_setup: tuple[Database, AppSettings],
    tmp_path: Path,
) -> None:
    database, settings = prompt_setup
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    template_dir.joinpath(DEFAULT_ASSESSMENT_PROMPT_FILENAME).write_text(
        "Configured default assessment prompt.",
        encoding="utf-8",
    )
    configured_settings = settings.model_copy(update={"template_dir": template_dir})

    DefaultAssessmentPromptService(database, configured_settings).ensure()

    assert (
        PromptService(database, configured_settings).get_active_text("assessment")
        == "Configured default assessment prompt."
    )


def test_repeated_installation_is_idempotent(
    prompt_setup: tuple[Database, AppSettings],
) -> None:
    database, settings = prompt_setup
    service = DefaultAssessmentPromptService(database, settings)

    assert service.ensure()
    assert not service.ensure()
    assert [
        asset.version for asset in PromptService(database, settings).list_versions("assessment")
    ] == [1]


def test_never_overwrites_an_existing_user_prompt(
    prompt_setup: tuple[Database, AppSettings],
) -> None:
    database, settings = prompt_setup
    prompt_service = PromptService(database, settings)
    prompt_service.save_text("assessment", "User-managed assessment prompt.")

    created = DefaultAssessmentPromptService(database, settings).ensure()

    assert not created
    assert prompt_service.get_active_text("assessment") == "User-managed assessment prompt."


def test_never_reactivates_a_retained_inactive_prompt(
    prompt_setup: tuple[Database, AppSettings],
) -> None:
    database, settings = prompt_setup
    prompt_service = PromptService(database, settings)
    saved = prompt_service.save_text("assessment", "Retained prompt.")
    with database.session() as session:
        stored = session.get(type(saved), saved.id)
        assert stored is not None
        stored.is_active = False

    created = DefaultAssessmentPromptService(database, settings).ensure()

    assert not created
    assert prompt_service.get_active_version("assessment") is None
    assert prompt_service.list_versions("assessment")[0].version == 1


def test_rejects_a_blank_packaged_template_without_creating_a_version(
    prompt_setup: tuple[Database, AppSettings],
    tmp_path: Path,
) -> None:
    database, settings = prompt_setup
    blank_template = tmp_path / "blank.txt"
    blank_template.write_text(" \n", encoding="utf-8")

    with pytest.raises(DefaultAssessmentPromptError, match="blank"):
        DefaultAssessmentPromptService(
            database,
            settings,
            template_path=blank_template,
        ).ensure()

    assert PromptService(database, settings).list_versions("assessment") == []


def _packaged_prompt_text() -> str:
    return (
        resources.files("job_application_copilot.assets")
        .joinpath(DEFAULT_ASSESSMENT_PROMPT_FILENAME)
        .read_text(encoding="utf-8")
    )
