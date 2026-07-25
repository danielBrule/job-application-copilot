"""Stable reference-asset domain values."""

from enum import StrEnum


class ReferenceAssetType(StrEnum):
    """Broad categories whose individual assets are identified by a stable key."""

    DOCUMENT = "DOCUMENT"
    PROMPT = "PROMPT"
    TEMPLATE = "TEMPLATE"
    REFERENCE_EXAMPLE = "REFERENCE_EXAMPLE"


class ReferenceAssetProcessingStatus(StrEnum):
    """Readiness of one immutable reference-asset version."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
