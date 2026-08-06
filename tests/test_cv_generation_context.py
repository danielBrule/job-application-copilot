"""Tests for CV-generation context policy helpers."""

from job_application_copilot.domain import DocumentBRoutingSetStatus
from job_application_copilot.services.cv_generation_context import _authorised_secondary
from job_application_copilot.services.document_b_routing import (
    ResolvedLanePacket,
    ResolvedRouting,
    RoutingSetSummary,
    SecondaryLaneConstraintPacket,
)


def test_assessment_secondary_lane_is_supporting_only_when_primary_route_allows_it() -> None:
    routing = ResolvedRouting(
        summary=RoutingSetSummary(
            routing_set_id=1,
            document_b_version=1,
            routing_config_version="1.0.0",
            routing_config_sha256="sha256:" + ("a" * 64),
            document_b_file_sha256="sha256:" + ("b" * 64),
            extracted_section_catalog_sha256="sha256:" + ("c" * 64),
            status=DocumentBRoutingSetStatus.VALIDATED,
            is_current=True,
        ),
        packet=ResolvedLanePacket(lane="PRIMARY_LANE", entries=(), conditional_guardrails=()),
        constraints=SecondaryLaneConstraintPacket(
            default_disposition_for_unlisted_lane="EXCLUDED",
            source_sections=(),
            allowed=("ALLOWED_SECONDARY",),
            cautious=({"lane": "CAUTIOUS_SECONDARY", "reason": "Supporting only."},),
        ),
    )

    assert _authorised_secondary(routing, "ALLOWED_SECONDARY") == "ALLOWED_SECONDARY"
    assert _authorised_secondary(routing, "CAUTIOUS_SECONDARY") == "CAUTIOUS_SECONDARY"
    assert _authorised_secondary(routing, "UNLISTED_SECONDARY") is None
    assert _authorised_secondary(routing, "PRIMARY_LANE") is None
