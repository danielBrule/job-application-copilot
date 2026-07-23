"""Application-wide logging configuration and structured event helpers."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from enum import StrEnum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from job_application_copilot.config import AppSettings

APPLICATION_LOGGER_NAME = "job_application_copilot"
BYTES_PER_MIB = 1024 * 1024
_HANDLER_MARKER = "_job_application_copilot_handler"
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_CONTEXT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class LogComponent(StrEnum):
    """Application processes that write to separate rotating files."""

    UI = "ui"
    WORKER = "worker"


class LoggingConfigurationError(RuntimeError):
    """Raised when application logging cannot be configured."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        super().__init__(f"Cannot configure application log '{path}': {reason}")


class UtcSecondFormatter(logging.Formatter):
    """Format log timestamps as UTC ISO-8601 values to whole seconds."""

    def formatTime(
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        del datefmt
        timestamp = datetime.fromtimestamp(record.created, UTC)
        return timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")


class ApplicationLogFilter(logging.Filter):
    """Add component context and redact configured secret values."""

    def __init__(self, component: LogComponent, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self.component = component.value
        self.secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        record.component = self.component
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        record.msg = message
        record.args = ()
        return True


def get_logger(name: str) -> logging.Logger:
    """Return a standard hierarchical application logger."""

    return logging.getLogger(name)


def configure_logging(
    settings: AppSettings,
    component: LogComponent,
    *,
    console_stream: TextIO | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> logging.Logger:
    """Configure console and component-specific rotating file logging."""

    log_file = settings.logs_folder / f"{component.value}.log"
    level = logging.getLevelNamesMapping()[settings.log_level]
    effective_max_bytes = (
        max_bytes if max_bytes is not None else settings.log_max_size_mb * BYTES_PER_MIB
    )
    effective_backup_count = backup_count if backup_count is not None else settings.log_backup_count
    formatter = UtcSecondFormatter(
        "%(asctime)s %(levelname)s component=%(component)s "
        "pid=%(process)d thread=%(threadName)s %(name)s %(message)s"
    )
    secret = (
        settings.openai_api_key.get_secret_value() if settings.openai_api_key is not None else ""
    )

    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=effective_max_bytes,
            backupCount=effective_backup_count,
            encoding="utf-8",
        )
    except OSError as error:
        raise LoggingConfigurationError(log_file, str(error)) from error

    console_handler = logging.StreamHandler(console_stream)
    application_filter = ApplicationLogFilter(component, (secret,))
    for handler in (console_handler, file_handler):
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handler.addFilter(application_filter)
        setattr(handler, _HANDLER_MARKER, True)

    logger = logging.getLogger(APPLICATION_LOGGER_NAME)
    reset_logging()
    logger.setLevel(level)
    logger.propagate = False
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


def reset_logging() -> None:
    """Close and remove handlers owned by the application configurator."""

    logger = logging.getLogger(APPLICATION_LOGGER_NAME)
    for handler in tuple(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **context: object,
) -> None:
    """Write a stable event name followed by sorted key/value context."""

    if not _EVENT_NAME.fullmatch(event):
        raise ValueError(f"Invalid log event name: {event!r}")

    invalid_keys = sorted(key for key in context if not _CONTEXT_NAME.fullmatch(key))
    if invalid_keys:
        raise ValueError(f"Invalid log context keys: {', '.join(invalid_keys)}")

    fields = " ".join(
        f"{key}={_format_context_value(value)}" for key, value in sorted(context.items())
    )
    message = event if not fields else f"{event} {fields}"
    logger.log(level, message, stacklevel=2)


def _format_context_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)
