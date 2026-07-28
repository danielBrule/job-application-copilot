"""Closed domain types for deterministic Document B lane routing."""

from enum import StrEnum


class CvLane(StrEnum):
    """Supported primary CV lanes shared by assessment and routing."""

    APPLIED_AI_DEPLOYMENT_LEADERSHIP = "APPLIED_AI_DEPLOYMENT_LEADERSHIP"
    AI_DEPLOYMENT_SOLUTION_OWNER = "AI_DEPLOYMENT_SOLUTION_OWNER"
    ZERO_TO_ONE_DATA_AI_SOLUTION_LEAD = "ZERO_TO_ONE_DATA_AI_SOLUTION_LEAD"
    DATA_AI_VALUE_CREATION = "DATA_AI_VALUE_CREATION"
    HEAD_OF_SOLUTIONS_ARCHITECTURE = "HEAD_OF_SOLUTIONS_ARCHITECTURE"
    HEAD_OF_DATA_ANALYTICS_AI = "HEAD_OF_DATA_ANALYTICS_AI"
    EXPERT_LED_COMMERCIAL_POST_SALES = "EXPERT_LED_COMMERCIAL_POST_SALES"
    TECHNICAL_PRODUCT_AI_PRODUCT_BUILDER = "TECHNICAL_PRODUCT_AI_PRODUCT_BUILDER"
    EXECUTION_FOCUSED_CTO_FIELD_CTO = "EXECUTION_FOCUSED_CTO_FIELD_CTO"


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
