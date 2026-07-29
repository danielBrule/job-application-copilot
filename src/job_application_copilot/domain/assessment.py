"""Stable assessment domain values."""

from enum import StrEnum


class AssessmentStatus(StrEnum):
    """Lifecycle of the single current assessment for a job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    ASSESSED = "ASSESSED"
    FAILED = "FAILED"


class AssessmentDecision(StrEnum):
    """Model recommendation for whether to pursue a job."""

    GO = "GO"
    CAUTION = "CAUTION"
    STRETCH = "STRETCH"
    NO_GO = "NO_GO"
