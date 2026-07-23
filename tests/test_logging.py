"""Tests for application-wide logging."""

from __future__ import annotations

import io
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from pydantic import SecretStr

from job_application_copilot.config import AppSettings
from job_application_copilot.observability import (
    LogComponent,
    LoggingConfigurationError,
    configure_logging,
    get_logger,
    log_event,
    reset_logging,
)

LOG_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO "
    r"component=ui pid=\d+ thread=MainThread "
    r"job_application_copilot\.test event_name count=2 label=\"résumé\"\n$"
)


@pytest.fixture(autouse=True)
def clean_application_logging() -> None:
    reset_logging()
    yield
    reset_logging()


def settings_under(logs_folder: Path, **overrides: object) -> AppSettings:
    return AppSettings(_env_file=None, logs_folder=logs_folder, **overrides)


def test_writes_same_structured_utf8_event_to_console_and_file(
    tmp_path: Path,
) -> None:
    settings = settings_under(tmp_path / "logs")
    settings.logs_folder.mkdir()
    console = io.StringIO()
    configure_logging(settings, LogComponent.UI, console_stream=console)

    log_event(
        get_logger("job_application_copilot.test"),
        logging.INFO,
        "event_name",
        label="résumé",
        count=2,
    )

    console_line = console.getvalue()
    file_line = (settings.logs_folder / "ui.log").read_text(encoding="utf-8")
    assert LOG_LINE.fullmatch(console_line)
    assert file_line == console_line
    assert "." not in console_line.split("Z", maxsplit=1)[0]


def test_respects_configured_log_level(tmp_path: Path) -> None:
    settings = settings_under(tmp_path / "logs", log_level="WARNING")
    settings.logs_folder.mkdir()
    configure_logging(settings, LogComponent.UI, console_stream=io.StringIO())
    logger = get_logger("job_application_copilot.test")

    log_event(logger, logging.INFO, "ignored_event")
    log_event(logger, logging.WARNING, "included_event")

    contents = (settings.logs_folder / "ui.log").read_text(encoding="utf-8")
    assert "ignored_event" not in contents
    assert "included_event" in contents


def test_uses_configured_rotation_policy(tmp_path: Path) -> None:
    settings = settings_under(
        tmp_path / "logs",
        log_max_size_mb=2,
        log_backup_count=3,
    )
    settings.logs_folder.mkdir()

    configured_logger = configure_logging(
        settings,
        LogComponent.UI,
        console_stream=io.StringIO(),
    )

    file_handler = next(
        handler
        for handler in configured_logger.handlers
        if isinstance(handler, RotatingFileHandler)
    )
    assert file_handler.maxBytes == 2 * 1024 * 1024
    assert file_handler.backupCount == 3


def test_ui_and_worker_use_separate_files(tmp_path: Path) -> None:
    settings = settings_under(tmp_path / "logs")
    settings.logs_folder.mkdir()

    configure_logging(settings, LogComponent.UI, console_stream=io.StringIO())
    log_event(get_logger("job_application_copilot.test"), logging.INFO, "ui_event")
    configure_logging(settings, LogComponent.WORKER, console_stream=io.StringIO())
    log_event(
        get_logger("job_application_copilot.test"),
        logging.INFO,
        "worker_event",
    )

    assert "ui_event" in (settings.logs_folder / "ui.log").read_text(encoding="utf-8")
    assert "worker_event" not in (settings.logs_folder / "ui.log").read_text(encoding="utf-8")
    assert "worker_event" in (settings.logs_folder / "worker.log").read_text(encoding="utf-8")


def test_reconfiguration_does_not_duplicate_messages(tmp_path: Path) -> None:
    settings = settings_under(tmp_path / "logs")
    settings.logs_folder.mkdir()

    configure_logging(settings, LogComponent.UI, console_stream=io.StringIO())
    configure_logging(settings, LogComponent.UI, console_stream=io.StringIO())
    log_event(get_logger("job_application_copilot.test"), logging.INFO, "once")

    contents = (settings.logs_folder / "ui.log").read_text(encoding="utf-8")
    assert contents.count("once") == 1


def test_rotates_component_file(tmp_path: Path) -> None:
    settings = settings_under(tmp_path / "logs")
    settings.logs_folder.mkdir()
    configure_logging(
        settings,
        LogComponent.UI,
        console_stream=io.StringIO(),
        max_bytes=180,
        backup_count=1,
    )
    logger = get_logger("job_application_copilot.test")

    for index in range(5):
        log_event(logger, logging.INFO, "rotation_event", index=index, value="x" * 40)

    assert (settings.logs_folder / "ui.log").exists()
    assert (settings.logs_folder / "ui.log.1").exists()


def test_redacts_configured_api_key(tmp_path: Path) -> None:
    api_key = "super-secret-api-key"
    settings = settings_under(
        tmp_path / "logs",
        openai_api_key=SecretStr(api_key),
    )
    settings.logs_folder.mkdir()
    console = io.StringIO()
    configure_logging(settings, LogComponent.UI, console_stream=console)

    get_logger("job_application_copilot.test").warning("credential=%s", api_key)

    file_contents = (settings.logs_folder / "ui.log").read_text(encoding="utf-8")
    assert api_key not in console.getvalue()
    assert api_key not in file_contents
    assert "[REDACTED]" in file_contents


def test_reports_unusable_log_destination(tmp_path: Path) -> None:
    logs_folder = tmp_path / "logs"
    logs_folder.write_text("not a directory", encoding="utf-8")
    settings = settings_under(logs_folder)

    with pytest.raises(LoggingConfigurationError) as captured:
        configure_logging(settings, LogComponent.UI, console_stream=io.StringIO())

    assert captured.value.path == logs_folder / "ui.log"
    assert "Cannot configure application log" in str(captured.value)


def test_rejects_unstructured_event_and_context_names(tmp_path: Path) -> None:
    settings = settings_under(tmp_path / "logs")
    settings.logs_folder.mkdir()
    configure_logging(settings, LogComponent.UI, console_stream=io.StringIO())
    logger = get_logger("job_application_copilot.test")

    with pytest.raises(ValueError, match="Invalid log event"):
        log_event(logger, logging.INFO, "Not Structured")

    with pytest.raises(ValueError, match="Invalid log context"):
        log_event(logger, logging.INFO, "valid_event", **{"Not Valid": "value"})
