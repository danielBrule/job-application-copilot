"""Tests for canonical, exact-path Document B routing manifests."""

from pathlib import Path

import pytest
import yaml
from conftest import (
    DOCUMENT_B_ROUTING_TEMPLATE,
    install_document_b_routing_config,
    make_routable_document_b,
)

from job_application_copilot.config import AppSettings
from job_application_copilot.config.document_b_routing import (
    RoutingConfigError,
    load_document_b_routing_config,
)
from job_application_copilot.domain import (
    DocumentBRouteRole,
    DocumentBRoutingSetStatus,
    ReferenceAssetType,
    RouteDeliveryMode,
    RouteInclusion,
)
from job_application_copilot.repositories import create_database
from job_application_copilot.services import (
    DocumentBRoutingError,
    DocumentBRoutingManifestService,
    DocumentBSectionService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


def make_context(
    tmp_path: Path,
) -> tuple[DocumentBRoutingManifestService, ReferenceAssetStorageService]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    install_document_b_routing_config(settings)
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    return (
        DocumentBRoutingManifestService(
            database,
            DocumentBSectionService(database, settings),
        ),
        ReferenceAssetStorageService(database, settings),
    )


def store_document_b(storage: ReferenceAssetStorageService) -> int:
    return storage.store(
        filename="document-b.docx",
        content=make_routable_document_b(),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    ).version


def test_canonical_config_has_exact_complete_closed_lane_catalogue() -> None:
    config = load_document_b_routing_config(DOCUMENT_B_ROUTING_TEMPLATE)

    assert config.lanes
    assert all(isinstance(lane, str) for lane in config.lanes)
    assert config.resolution.strategy == "EXACT_HEADING_PATH_AFTER_NORMALIZATION"
    assert config.resolution.case_sensitive
    assert not config.resolution.allow_fuzzy_matching
    assert not config.resolution.allow_substring_matching
    assert not config.resolution.allow_model_resolution


def test_missing_private_config_points_to_committed_template(tmp_path: Path) -> None:
    missing_path = tmp_path / "data" / "reference" / "routing" / "routes.yaml"

    with pytest.raises(RoutingConfigError) as captured:
        load_document_b_routing_config(missing_path)

    assert str(missing_path) in str(captured.value)
    assert "templates/document-b-lane-routes.template.yaml" in str(captured.value)


def test_rejects_secondary_reference_to_unconfigured_lane(tmp_path: Path) -> None:
    source = yaml.safe_load(DOCUMENT_B_ROUTING_TEMPLATE.read_text(encoding="utf-8"))
    source["lanes"].pop("HEAD_OF_SOLUTIONS_ARCHITECTURE")
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(yaml.safe_dump(source), encoding="utf-8")

    with pytest.raises(RoutingConfigError, match="unconfigured secondary lanes"):
        load_document_b_routing_config(config_path)


def test_generates_and_resolves_three_materially_different_lanes(tmp_path: Path) -> None:
    service, storage = make_context(tmp_path)
    version = store_document_b(storage)

    generated = service.generate(version)

    assert generated.status is DocumentBRoutingSetStatus.VALIDATED
    assert generated.is_current
    for lane in (
        "APPLIED_AI_DEPLOYMENT_LEADERSHIP",
        "HEAD_OF_SOLUTIONS_ARCHITECTURE",
        "HEAD_OF_DATA_ANALYTICS_AI",
    ):
        resolved = service.resolve(version, lane)
        roles = [entry.role for entry in resolved.packet.entries]
        assert roles.count(DocumentBRouteRole.SUMMARY) == 1
        assert roles.count(DocumentBRouteRole.EXPERIENCE_FRAMING) == 1
        assert roles.count(DocumentBRouteRole.POSITIONING_PLAYBOOK) == 1
        assert DocumentBRouteRole.PHASE_2_BRIEF_TEMPLATE in roles
        assert DocumentBRouteRole.PHASE_3_CV_TEMPLATE in roles
        assert any(
            entry.role is DocumentBRouteRole.BULLET_LIBRARY
            and entry.inclusion is RouteInclusion.OPTIONAL
            for entry in resolved.packet.entries
        )


def test_packet_distinguishes_direct_context_and_vector_scopes(tmp_path: Path) -> None:
    service, storage = make_context(tmp_path)
    version = store_document_b(storage)
    generated = service.generate(version)

    packet = service.resolve(version, "HEAD_OF_SOLUTIONS_ARCHITECTURE").packet

    assert generated.routing_config_sha256.startswith("sha256:")
    assert generated.document_b_file_sha256.startswith("sha256:")
    assert generated.extracted_section_catalog_sha256.startswith("sha256:")
    assert all(
        entry.delivery_mode is RouteDeliveryMode.DIRECT_CONTEXT
        for entry in packet.entries
        if entry.role is not DocumentBRouteRole.BULLET_LIBRARY
    )
    assert all(
        entry.delivery_mode is RouteDeliveryMode.VECTOR_SCOPE_REQUIRED
        for entry in packet.entries
        if entry.role is DocumentBRouteRole.BULLET_LIBRARY
        and entry.inclusion is RouteInclusion.MANDATORY
    )
    assert all(
        entry.delivery_mode is RouteDeliveryMode.VECTOR_SCOPE_OPTIONAL
        for entry in packet.entries
        if entry.role is DocumentBRouteRole.BULLET_LIBRARY
        and entry.inclusion is RouteInclusion.OPTIONAL
    )


def test_genai_scope_carries_conditional_guardrail_dependencies(tmp_path: Path) -> None:
    service, storage = make_context(tmp_path)
    version = store_document_b(storage)
    service.generate(version)

    packet = service.resolve(version, "DATA_AI_VALUE_CREATION").packet

    genai_rule = next(
        rule
        for rule in packet.conditional_guardrails
        if rule.trigger_logical_ids == ("bullets.genai_llm_talk_to_data",)
    )
    assert genai_rule.required_logical_ids == (
        "skills.genai_confidence_rule",
        "guardrails.talk_to_data_mvp",
        "guardrails.applied_genai",
    )
    assert genai_rule.required_section_ids == (
        "skills-and-keyword-bank-keywords-to-use-carefully-genai-confidence-rule",
        "cv-assembly-rules-and-anti-overclaiming-guardrails-anti-overclaiming-"
        "guardrails-t2d-scope-and-external-production-boundary",
        "cv-assembly-rules-and-anti-overclaiming-guardrails-applied-genai-positioning-guidance",
    )
    assert service.conditional_guardrails_for_selection(
        version,
        "DATA_AI_VALUE_CREATION",
        frozenset({"bullets.genai_llm_talk_to_data"}),
    ) == (genai_rule,)


def test_supporting_routes_clearly_disallow_primary_lane_selection() -> None:
    config = load_document_b_routing_config(DOCUMENT_B_ROUTING_TEMPLATE)

    incomplete = config.supporting_routes["HEAD_OF_DATA_PLATFORMS_TECHNOLOGY"]
    supporting = config.supporting_routes["SOFTWARE_ENGINEERING_FOUNDATION"]

    assert incomplete.category == "INCOMPLETE_PRIMARY_LANE"
    assert supporting.category == "OPTIONAL_SUPPORTING_CONTENT"
    assert not incomplete.primary_lane_selectable
    assert not supporting.primary_lane_selectable
    assert incomplete.secondary_support_selectable
    assert supporting.secondary_support_selectable


def test_regeneration_supersedes_prior_current_set(tmp_path: Path) -> None:
    service, storage = make_context(tmp_path)
    version = store_document_b(storage)

    first = service.generate(version)
    second = service.generate(version)

    assert first.routing_set_id != second.routing_set_id
    assert second.is_current
    assert service.resolve(version, "HEAD_OF_SOLUTIONS_ARCHITECTURE").summary == second


def test_exact_heading_case_mismatch_is_retained_as_invalid(
    tmp_path: Path,
) -> None:
    service, storage = make_context(tmp_path)
    version = store_document_b(storage)
    source = yaml.safe_load(service.config_path.read_text(encoding="utf-8"))
    source["section_catalog"]["summary.head_of_solutions_architecture"]["heading_path"][-1] = (
        "head of solutions architecture / data-ai architecture"
    )
    invalid_path = tmp_path / "invalid.yaml"
    invalid_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    service.config_path = invalid_path

    with pytest.raises(DocumentBRoutingError, match="cannot resolve exact heading path"):
        service.generate(version)

    reference_asset_id = service._reference_asset(version)[0]
    with service.database.session() as session:
        from job_application_copilot.repositories.document_b_routing_repository import (
            DocumentBRoutingRepository,
        )

        attempts = DocumentBRoutingRepository(session).list_for_asset(reference_asset_id)
        assert attempts[0].status is DocumentBRoutingSetStatus.INVALID
        assert not attempts[0].is_current
        assert "head of solutions architecture" in (attempts[0].validation_error or "")


def test_routing_set_cannot_be_used_for_another_document_b_version(tmp_path: Path) -> None:
    service, storage = make_context(tmp_path)
    first = store_document_b(storage)
    second = storage.store(
        filename="document-b-2.docx",
        content=make_routable_document_b("Second version."),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    ).version
    service.generate(first)

    with pytest.raises(DocumentBRoutingError, match="no current routing set"):
        service.resolve(second, "HEAD_OF_SOLUTIONS_ARCHITECTURE")


def test_new_document_b_version_with_unchanged_structure_generates_its_own_manifest(
    tmp_path: Path,
) -> None:
    service, storage = make_context(tmp_path)
    first = store_document_b(storage)
    second = storage.store(
        filename="document-b-2.docx",
        content=make_routable_document_b("Same structure, revised wording."),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    ).version

    first_summary = service.generate(first)
    second_summary = service.generate(second)

    assert first_summary.document_b_version == first
    assert second_summary.document_b_version == second
    assert (
        first_summary.extracted_section_catalog_sha256
        != second_summary.extracted_section_catalog_sha256
    )
    assert service.resolve(second, "HEAD_OF_SOLUTIONS_ARCHITECTURE").summary == second_summary


def test_toc_renumbering_does_not_change_exact_heading_resolution(tmp_path: Path) -> None:
    service, storage = make_context(tmp_path)
    version = store_document_b(storage)
    source = yaml.safe_load(service.config_path.read_text(encoding="utf-8"))
    for catalog in source["section_catalog"].values():
        catalog["toc_hint"] = "99.99"
    config_path = tmp_path / "renumbered-toc.yaml"
    config_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    service.config_path = config_path

    assert service.generate(version).status is DocumentBRoutingSetStatus.VALIDATED


def test_renamed_mandatory_heading_fails_without_fallback(tmp_path: Path) -> None:
    service, storage = make_context(tmp_path)
    original = make_routable_document_b()
    from io import BytesIO

    from docx import Document

    document = Document(BytesIO(original))
    next(
        paragraph
        for paragraph in document.paragraphs
        if paragraph.text == "CV generation workflow and rules"
    ).text = "Renamed CV generation workflow and rules"
    buffer = BytesIO()
    document.save(buffer)
    version = storage.store(
        filename="renamed.docx",
        content=buffer.getvalue(),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    ).version

    with pytest.raises(DocumentBRoutingError, match="CV generation workflow and rules"):
        service.generate(version)


def test_missing_mandatory_heading_fails_validation(tmp_path: Path) -> None:
    service, storage = make_context(tmp_path)
    version = storage.store(
        filename="missing.docx",
        content=make_routable_document_b(
            omitted_heading_paths=frozenset({("CV generation workflow and rules",)})
        ),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    ).version

    with pytest.raises(DocumentBRoutingError, match="CV generation workflow and rules"):
        service.generate(version)


def test_accepts_additional_installation_configured_lane(tmp_path: Path) -> None:
    source = yaml.safe_load(DOCUMENT_B_ROUTING_TEMPLATE.read_text(encoding="utf-8"))
    source["lanes"]["CUSTOM_INSTALLATION_LANE"] = source["lanes"]["HEAD_OF_DATA_ANALYTICS_AI"]
    config_path = tmp_path / "unsupported-lane.yaml"
    config_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")

    config = load_document_b_routing_config(config_path)

    assert "CUSTOM_INSTALLATION_LANE" in config.lanes


def test_generates_persists_and_resolves_installation_configured_lane(
    tmp_path: Path,
) -> None:
    service, storage = make_context(tmp_path)
    source = yaml.safe_load(service.config_path.read_text(encoding="utf-8"))
    source["lanes"]["CUSTOM_INSTALLATION_LANE"] = source["lanes"]["HEAD_OF_DATA_ANALYTICS_AI"]
    service.config_path.write_text(
        yaml.safe_dump(source, sort_keys=False),
        encoding="utf-8",
    )
    version = store_document_b(storage)

    service.generate(version)
    resolved = service.resolve(version, "CUSTOM_INSTALLATION_LANE")

    assert resolved.packet.lane == "CUSTOM_INSTALLATION_LANE"
