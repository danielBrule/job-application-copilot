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
    _authorised_mandate_support,
    _authorised_secondary,
    _authorised_supporting_lane,
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
            "mandate_coverage": [
                {
                    "mandate_dimension_id": "delivery",
                    "planned_evidence": "Validated evidence.",
                    "coverage_status": "COVERED",
                }
            ],
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


def test_secondary_cv_angle_can_authorise_support_without_secondary_role_family() -> None:
    primary = ResolvedRouting(
        summary=routing().summary,
        packet=ResolvedLanePacket(lane="PRIMARY_LANE", entries=(), conditional_guardrails=()),
        constraints=SecondaryLaneConstraintPacket(
            default_disposition_for_unlisted_lane="EXCLUDED",
            source_sections=(),
            allowed=("COMMERCIAL_POST_SALES",),
            cautious=(),
        ),
    )
    assessment = SimpleNamespace(
        secondary_role_family=None,
        secondary_cv_angle="COMMERCIAL_POST_SALES",
        material_mandate_dimensions=[
            {
                "should_shape_cv": True,
                "evidence_strength": "DIRECT",
            }
        ],
    )

    assert _authorised_supporting_lane(primary, assessment) == "COMMERCIAL_POST_SALES"


@pytest.mark.parametrize(
    ("angle", "strength", "expected"),
    [
        (None, "DIRECT", None),  # Pure single-lane role.
        ("COMMERCIAL_POST_SALES", "NONE", None),  # Unsupported secondary dimension.
        ("COMMERCIAL_POST_SALES", "WEAK", None),  # Hunter-sales evidence must not inflate fit.
        ("COMMERCIAL_POST_SALES", "ADJACENT", "COMMERCIAL_POST_SALES"),  # Hybrid role.
        ("COMMERCIAL_POST_SALES", "DIRECT", "COMMERCIAL_POST_SALES"),  # Valid angle.
    ],
)
def test_supporting_angle_requires_credible_material_evidence(
    angle: str | None, strength: str, expected: str | None
) -> None:
    primary = ResolvedRouting(
        summary=routing().summary,
        packet=ResolvedLanePacket(lane="PRIMARY_LANE", entries=(), conditional_guardrails=()),
        constraints=SecondaryLaneConstraintPacket(
            default_disposition_for_unlisted_lane="EXCLUDED",
            source_sections=(),
            allowed=("COMMERCIAL_POST_SALES",),
            cautious=(),
        ),
    )
    assessment = SimpleNamespace(
        secondary_role_family=None,
        secondary_cv_angle=angle,
        material_mandate_dimensions=[{"should_shape_cv": True, "evidence_strength": strength}],
    )

    assert _authorised_supporting_lane(primary, assessment) == expected


def test_credible_mandate_dimension_authorises_only_its_scoped_bullet_library() -> None:
    commercial = ResolvedRouteEntry(
        logical_id="bullets.expert_commercial_post_sales",
        section_id="commercial-root",
        heading="Commercial",
        heading_path=("Bullets", "Commercial"),
        role=DocumentBRouteRole.BULLET_LIBRARY,
        inclusion=RouteInclusion.MANDATORY,
        delivery_mode=RouteDeliveryMode.VECTOR_SCOPE_REQUIRED,
        include_descendants=True,
        expanded_section_ids=("commercial-root",),
    )
    primary = ResolvedRouting(
        summary=routing().summary,
        packet=ResolvedLanePacket(
            lane="PRIMARY_LANE",
            entries=(),
            mandate_support_categories={"COMMERCIAL_POST_SALES": (commercial,)},
            conditional_guardrails=(),
        ),
        constraints=routing().constraints,
    )
    assessment = SimpleNamespace(
        material_mandate_dimensions=[
            {
                "should_shape_cv": True,
                "evidence_strength": "DIRECT",
                "support_categories": ["COMMERCIAL_POST_SALES"],
            }
        ]
    )

    assert _authorised_mandate_support(primary, assessment) == (commercial,)


@pytest.mark.parametrize("strength", ["WEAK", "NONE"])
def test_weak_or_unsupported_mandate_does_not_authorise_thematic_support(
    strength: str,
) -> None:
    primary = ResolvedRouting(
        summary=routing().summary,
        packet=ResolvedLanePacket(
            lane="PRIMARY_LANE",
            entries=(),
            mandate_support_categories={},
            conditional_guardrails=(),
        ),
        constraints=routing().constraints,
    )
    assessment = SimpleNamespace(
        material_mandate_dimensions=[
            {
                "should_shape_cv": True,
                "evidence_strength": strength,
                "support_categories": ["COMMERCIAL_POST_SALES"],
            }
        ]
    )

    assert _authorised_mandate_support(primary, assessment) == ()


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
            brief(selected_sections=frozenset({"not-authorised"})), routing(), None, 1, 1, ()
        )


def test_later_stages_accept_primary_lane_scoped_sections_selected_by_stage_one() -> None:
    primary = routing()
    scoped_entry = ResolvedRouteEntry(
        logical_id="bullet-library",
        section_id="bullet-root",
        heading="Bullet library",
        heading_path=("Bullets",),
        role=DocumentBRouteRole.BULLET_LIBRARY,
        inclusion=RouteInclusion.MANDATORY,
        delivery_mode=RouteDeliveryMode.VECTOR_SCOPE_REQUIRED,
        include_descendants=True,
        expanded_section_ids=("bullet-root",),
    )
    primary = ResolvedRouting(
        summary=primary.summary,
        packet=ResolvedLanePacket(
            lane=primary.packet.lane,
            entries=primary.packet.entries + (scoped_entry,),
            conditional_guardrails=(),
        ),
        constraints=primary.constraints,
    )

    CvGenerationContextBuilder._validate_brief(
        brief(selected_sections=frozenset({"bullet-root"})), primary, None, 1, 1, ()
    )
