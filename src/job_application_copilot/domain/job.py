"""Stable job domain values."""

from enum import StrEnum


class Location(StrEnum):
    """Supported job locations."""

    UK = "UK"
    FR = "FR"
    CH = "CH"


class Language(StrEnum):
    """Supported job and CV languages."""

    EN = "EN"
    FR = "FR"


class UserDecision(StrEnum):
    """Human application decision, independent of model recommendations."""

    UNDECIDED = "UNDECIDED"
    PURSUE = "PURSUE"
    DO_NOT_PURSUE = "DO_NOT_PURSUE"
