"""Shared SQLAlchemy model helpers."""

from datetime import UTC, datetime
from enum import StrEnum


def utc_now() -> datetime:
    """Return a timezone-naive UTC timestamp to whole seconds for SQLite."""

    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def enum_values[EnumMember: StrEnum](enum_type: type[EnumMember]) -> list[str]:
    """Store stable enum values rather than Python member names."""

    return [member.value for member in enum_type]
