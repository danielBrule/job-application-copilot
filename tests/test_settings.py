"""Tests for typed application configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from job_application_copilot.config import AppSettings, Language, Location

SETTING_ENVIRONMENT_VARIABLES = (
    "JAC_DATA_DIR",
    "JAC_DATABASE_PATH",
    "JAC_CV_FOLDER",
    "JAC_REFERENCE_FOLDER",
    "JAC_ASSESSMENT_WORKER_COUNT",
    "JAC_CV_WORKER_COUNT",
    "JAC_DEFAULT_SOURCE",
    "JAC_DEFAULT_LOCATION",
    "JAC_DEFAULT_LANGUAGE",
    "OPENAI_API_KEY",
    "JAC_OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep settings tests independent from the developer's environment."""

    for variable in SETTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_defaults_are_safe_and_typed() -> None:
    settings = AppSettings(_env_file=None)

    assert settings.data_dir == Path("data")
    assert settings.database_path == Path("data/database/job_application_copilot.db")
    assert settings.cv_folder == Path("data/cvs")
    assert settings.reference_folder == Path("data/reference")
    assert settings.openai_api_key is None
    assert settings.assessment_worker_count == 1
    assert settings.cv_worker_count == 1
    assert settings.default_source == "LinkedIn"
    assert settings.default_location is Location.UK
    assert settings.default_language is Language.EN


def test_data_paths_are_derived_from_data_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", "private")

    settings = AppSettings(_env_file=None)

    assert settings.data_dir == Path("private")
    assert settings.database_path == Path("private/database/job_application_copilot.db")
    assert settings.cv_folder == Path("private/cvs")
    assert settings.reference_folder == Path("private/reference")


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", "ignored-for-specific-paths")
    monkeypatch.setenv("JAC_DATABASE_PATH", "private/copilot.sqlite3")
    monkeypatch.setenv("JAC_CV_FOLDER", "private/cvs")
    monkeypatch.setenv("JAC_REFERENCE_FOLDER", "private/reference")
    monkeypatch.setenv("JAC_ASSESSMENT_WORKER_COUNT", "3")
    monkeypatch.setenv("JAC_CV_WORKER_COUNT", "5")
    monkeypatch.setenv("JAC_DEFAULT_SOURCE", "Company website")
    monkeypatch.setenv("JAC_DEFAULT_LOCATION", "CH")
    monkeypatch.setenv("JAC_DEFAULT_LANGUAGE", "FR")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")

    settings = AppSettings(_env_file=None)

    assert settings.data_dir == Path("ignored-for-specific-paths")
    assert settings.database_path == Path("private/copilot.sqlite3")
    assert settings.cv_folder == Path("private/cvs")
    assert settings.reference_folder == Path("private/reference")
    assert settings.assessment_worker_count == 3
    assert settings.cv_worker_count == 5
    assert settings.default_source == "Company website"
    assert settings.default_location is Location.CH
    assert settings.default_language is Language.FR
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "secret-value"
    assert "secret-value" not in repr(settings)


def test_loads_dotenv_and_environment_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JAC_DEFAULT_LOCATION=FR\nJAC_ASSESSMENT_WORKER_COUNT=2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JAC_ASSESSMENT_WORKER_COUNT", "4")

    settings = AppSettings(_env_file=env_file)

    assert settings.default_location is Location.FR
    assert settings.assessment_worker_count == 4


@pytest.mark.parametrize("value", ["0", "-1", "6", "not-an-integer"])
@pytest.mark.parametrize(
    "variable",
    ["JAC_ASSESSMENT_WORKER_COUNT", "JAC_CV_WORKER_COUNT"],
)
def test_rejects_invalid_worker_counts(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError, match="worker_count"):
        AppSettings(_env_file=None)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("JAC_DEFAULT_LOCATION", "DE"),
        ("JAC_DEFAULT_LANGUAGE", "DE"),
    ],
)
def test_rejects_unsupported_defaults(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError):
        AppSettings(_env_file=None)


def test_loading_settings_does_not_create_private_directories(tmp_path: Path) -> None:
    database_path = tmp_path / "database" / "copilot.db"
    cv_folder = tmp_path / "cvs"
    reference_folder = tmp_path / "reference"

    AppSettings(
        _env_file=None,
        database_path=database_path,
        cv_folder=cv_folder,
        reference_folder=reference_folder,
    )

    assert not database_path.parent.exists()
    assert not cv_folder.exists()
    assert not reference_folder.exists()
