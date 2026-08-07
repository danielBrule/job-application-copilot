"""Domain values and lifecycle rules for one job's active CV."""

from collections.abc import Mapping
from enum import StrEnum


class CvSource(StrEnum):
    GENERATED = "GENERATED"
    UPLOADED = "UPLOADED"


class CvStatus(StrEnum):
    SELECTED = "SELECTED"
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    FAILED = "FAILED"
    APPROVED = "APPROVED"


ALLOWED_CV_TRANSITIONS: Mapping[CvStatus, frozenset[CvStatus]] = {
    CvStatus.SELECTED: frozenset({CvStatus.PENDING, CvStatus.FAILED}),
    CvStatus.PENDING: frozenset({CvStatus.GENERATING, CvStatus.FAILED}),
    CvStatus.GENERATING: frozenset({CvStatus.READY_FOR_REVIEW, CvStatus.FAILED}),
    CvStatus.READY_FOR_REVIEW: frozenset({CvStatus.APPROVED, CvStatus.FAILED}),
    CvStatus.FAILED: frozenset({CvStatus.PENDING}),
    CvStatus.APPROVED: frozenset(),
}


def is_valid_cv_transition(current: CvStatus, target: CvStatus) -> bool:
    """Return whether an active-CV lifecycle transition is explicitly permitted."""

    return target in ALLOWED_CV_TRANSITIONS[current]
