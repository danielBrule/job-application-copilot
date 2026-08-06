"""Tests for CV-generation context policy helpers."""

from types import SimpleNamespace

import pytest

from job_application_copilot.domain import (
    DocumentBRouteRole,
    DocumentBRoutingSetStatus,
    RouteDeliveryMode,
    RouteInclusion,
)
from job_application_copilot.services.cv_generation_context import (
    CvGenerationBriefInput,
    CvGenerationContextBuilder,
    CvGenerationContextError,
    _authorised_secondary,
)
from job_application_copilot.services.document_b_routing import (
    ResolvedLanePacket,
    ResolvedRouteEntry,
    ResolvedRouting,
    RoutingSetSummary,
    SecondaryLaneConstraintPacket,
)


def routing() -> ResolvedRouting:
    return ResolvedRouting(
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
        packet=ResolvedLanePacket(
            lane="PRIMARY_LANE",
            entries=(
                ResolvedRouteEntry(
                    logical_id="summary",
                    section_id="summary-root",
                    heading="Summary",
                    heading_path=("Summary",),
                    role=DocumentBRouteRole.SUMMARY,
                    inclusion=RouteInclusion.MANDATORY,
                    delivery_mode=RouteDeliveryMode.DIRECT_CONTEXT,
                    include_descendants=True,
                    expanded_section_ids=("summary-root", "summary-child"),
                ),
                ResolvedRouteEntry(
                    logical_id="guardrails",
                    section_id="guardrails",
                    heading="Guardrails",
                    heading_path=("Guardrails",),
                    role=DocumentBRouteRole.GUARDRAIL,
                    inclusion=RouteInclusion.MANDATORY,
                    delivery_mode=RouteDeliveryMode.DIRECT_CONTEXT,
                    include_descendants=False,
                    expanded_section_ids=("guardrails",),
                ),
            ),
            conditional_guardrails=(),
        ),
        constraints=SecondaryLaneConstraintPacket(
            default_disposition_for_unlisted_lane="EXCLUDED",
            source_sections=(),
            allowed=(),
            cautious=(),
        ),
    )


def brief(*, selected_sections: frozenset[str]) -> CvGenerationBriefInput:
    return CvGenerationBriefInput(
        document_a_version=1,
        document_b_version=1,
        routing_set_id=1,
        output={
            "target_cv_lane": "PRIMARY_LANE",
            "primary_narrative": "Primary narrative.",
            "evidence_to_lead_with": ["Validated evidence."],
            "professional_summary_direction": "Lead with evidence.",
            "independent_work_treatment": "Frame cautiously.",
            "skills_section_direction": "Use evidenced skills.",
            "overclaiming_risks": [],
            "proposed_cv_structure": ["Profile"],
            "selected_section_ids": selected_sections,
            "guardrail_ids": ["guardrails"],
        },
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


def test_later_stages_receive_only_brief_selected_sections_and_guardrails() -> None:
    builder = object.__new__(CvGenerationContextBuilder)
    builder.sections = SimpleNamespace(
        require_section=lambda version, section_id: SimpleNamespace(
            section_id=section_id, section_text=f"{section_id} text"
        )
    )

    text = builder._mandatory_document_b_text(
        routing(),
        1,
        selected_section_ids=frozenset({"summary-child"}),
        guardrail_ids=frozenset({"guardrails"}),
    )

    assert '"section_id":"summary-child"' in text
    assert '"section_id":"guardrails"' in text
    assert "summary-root" not in text


def test_rejects_brief_sections_not_available_as_direct_context() -> None:
    with pytest.raises(CvGenerationContextError, match="unauthorised"):
        CvGenerationContextBuilder._validate_brief(
            brief(selected_sections=frozenset({"not-authorised"})), routing(), 1, 1, ()
        )
