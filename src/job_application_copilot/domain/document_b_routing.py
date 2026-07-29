"""Domain types for deterministic Document B lane routing."""

from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

LaneId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]


class DocumentBRoutingSetStatus(StrEnum):
    """Lifecycle state of an immutable generated routing set."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    INVALID = "INVALID"
    SUPERSEDED = "SUPERSEDED"


class DocumentBRouteRole(StrEnum):
    """Supported semantic roles for routed Document B sections."""

    WORKFLOW = "WORKFLOW"
    SUMMARY = "SUMMARY"
    EXPERIENCE_FRAMING = "EXPERIENCE_FRAMING"
    POSITIONING_PLAYBOOK = "POSITIONING_PLAYBOOK"
    BULLET_LIBRARY = "BULLET_LIBRARY"
    SKILLS = "SKILLS"
    GUARDRAIL = "GUARDRAIL"
    PHASE_2_BRIEF_TEMPLATE = "PHASE_2_BRIEF_TEMPLATE"
    PHASE_3_CV_TEMPLATE = "PHASE_3_CV_TEMPLATE"
    SUPPORTING_EXPERIENCE = "SUPPORTING_EXPERIENCE"


class RouteInclusion(StrEnum):
    """Whether a routed root is always included or retrieval-eligible."""

    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"


class RouteDeliveryMode(StrEnum):
    """How authorised Document B material reaches a later pipeline stage."""

    DIRECT_CONTEXT = "DIRECT_CONTEXT"
    VECTOR_SCOPE_REQUIRED = "VECTOR_SCOPE_REQUIRED"
    VECTOR_SCOPE_OPTIONAL = "VECTOR_SCOPE_OPTIONAL"


class SecondaryLaneDisposition(StrEnum):
    """Permitted treatment of a secondary lane."""

    ALLOWED = "ALLOWED"
    CAUTION = "CAUTION"
    EXCLUDED = "EXCLUDED"
