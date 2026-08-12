"""Generate and resolve deterministic, version-bound Document B routing manifests."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from job_application_copilot.config.document_b_routing import (
    DocumentBRoutingConfig,
    LaneRouteConfig,
    RoutingConfigError,
    load_document_b_routing_config,
    referenced_logical_section_ids,
)
from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    DocumentBRouteRole,
    DocumentBRoutingSetStatus,
    LaneId,
    RouteDeliveryMode,
    RouteInclusion,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.document_b_routing_repository import (
    DocumentBRoutingRepository,
)
from job_application_copilot.repositories.models import (
    DocumentBLaneRoute,
    DocumentBRoutingSet,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.document_b_sections import (
    DocumentBSectionRecord,
    DocumentBSectionService,
)


class DocumentBRoutingError(ValueError):
    """Raised when routing cannot be generated or resolved safely."""


class ResolvedRouteEntry(BaseModel):
    """One configured root and the exact extracted sections it authorises."""

    model_config = ConfigDict(frozen=True)

    logical_id: str
    section_id: str
    heading: str
    heading_path: tuple[str, ...]
    role: DocumentBRouteRole
    inclusion: RouteInclusion
    delivery_mode: RouteDeliveryMode
    include_descendants: bool
    expanded_section_ids: tuple[str, ...]


class SecondaryLaneConstraintPacket(BaseModel):
    """Persisted canonical secondary-lane restrictions for one primary lane."""

    model_config = ConfigDict(frozen=True)

    default_disposition_for_unlisted_lane: str
    source_sections: tuple[str, ...]
    allowed: tuple[LaneId, ...]
    cautious: tuple[dict[str, str], ...]


class ConditionalGuardrailPacket(BaseModel):
    """Guardrails required when a later Phase 2 selection uses a trigger scope."""

    model_config = ConfigDict(frozen=True)

    trigger_logical_ids: tuple[str, ...]
    required_logical_ids: tuple[str, ...]
    required_section_ids: tuple[str, ...]


class ResolvedLanePacket(BaseModel):
    """Validated ordered route for one exact lane and Document B version."""

    model_config = ConfigDict(frozen=True)

    lane: LaneId
    entries: tuple[ResolvedRouteEntry, ...]
    conditional_guardrails: tuple[ConditionalGuardrailPacket, ...]


@dataclass(frozen=True, slots=True)
class RoutingSetSummary:
    routing_set_id: int
    document_b_version: int
    routing_config_version: str
    routing_config_sha256: str
    document_b_file_sha256: str
    extracted_section_catalog_sha256: str
    status: DocumentBRoutingSetStatus
    is_current: bool


@dataclass(frozen=True, slots=True)
class ResolvedRouting:
    summary: RoutingSetSummary
    packet: ResolvedLanePacket
    constraints: SecondaryLaneConstraintPacket


class DocumentBRoutingManifestService:
    """Compile canonical exact paths into immutable version-specific lane packets."""

    def __init__(
        self,
        database: Database,
        section_service: DocumentBSectionService,
        *,
        config_path: Path | None = None,
    ) -> None:
        self.database = database
        self.section_service = section_service
        self.config_path = config_path or section_service.settings.document_b_routing_config_path

    def generate(self, version: int) -> RoutingSetSummary:
        """Generate a new current validated set, retaining failed attempts."""

        reference_asset_id, document_b_file_sha256 = self._reference_asset(version)
        try:
            config = load_document_b_routing_config(self.config_path)
            config_version = config.routing_config_version
            routing_config_sha256 = _sha256(self.config_path.read_bytes())
        except RoutingConfigError as error:
            routing_set_id = self._create_draft(
                reference_asset_id,
                "unknown",
                _sha256(self.config_path.read_bytes())
                if self.config_path.is_file()
                else "sha256:unknown",
                document_b_file_sha256,
                "sha256:unknown",
            )
            self._invalidate(routing_set_id, str(error))
            raise DocumentBRoutingError(str(error)) from error

        routing_set_id = self._create_draft(
            reference_asset_id,
            config_version,
            routing_config_sha256,
            document_b_file_sha256,
            "sha256:pending",
        )
        try:
            sections = self.section_service.list_sections(version)
            packets = _compile_packets(config, sections)
            self._validate_version_unchanged(version, reference_asset_id)
            return self._persist_validated(
                routing_set_id,
                reference_asset_id,
                version,
                config,
                packets,
                _catalog_hash(sections),
            )
        except Exception as error:
            message = str(error) or "Document B routing validation failed."
            self._invalidate(routing_set_id, message)
            if isinstance(error, DocumentBRoutingError):
                raise
            raise DocumentBRoutingError(message) from error

    def validate_config(self, version: int, config: DocumentBRoutingConfig) -> None:
        """Validate authored routes against one retained Document B without persistence."""

        sections = self.section_service.extract(version)
        _compile_packets(config, sections)

    def resolve(self, version: int, lane: LaneId) -> ResolvedRouting:
        """Resolve an exact lane from the current validated set for one version."""

        reference_asset_id, _ = self._reference_asset(version)
        with self.database.session() as session:
            repository = DocumentBRoutingRepository(session)
            routing_set = repository.get_current(reference_asset_id)
            if routing_set is None:
                raise DocumentBRoutingError(
                    f"Document B version {version} has no current routing set."
                )
            if routing_set.status is not DocumentBRoutingSetStatus.VALIDATED:
                raise DocumentBRoutingError(
                    f"Document B version {version} current routing set is "
                    f"{routing_set.status.value}, not VALIDATED."
                )
            route = repository.get_route(routing_set.id, lane)
            if route is None:
                raise DocumentBRoutingError(
                    f"CV lane '{lane}' is unsupported for Document B version {version}."
                )
            return ResolvedRouting(
                summary=_summary(routing_set, version),
                packet=ResolvedLanePacket.model_validate_json(route.ordered_route_json),
                constraints=SecondaryLaneConstraintPacket.model_validate_json(
                    route.secondary_lane_constraints_json
                ),
            )

    def list_current_routes(self, version: int) -> tuple[ResolvedRouting, ...]:
        """Return every supported lane from one current validated set."""

        reference_asset_id, _ = self._reference_asset(version)
        with self.database.session() as session:
            repository = DocumentBRoutingRepository(session)
            routing_set = repository.get_current(reference_asset_id)
            if routing_set is None:
                raise DocumentBRoutingError(
                    f"Document B version {version} has no current routing set."
                )
            lane_ids = tuple(route.lane_id for route in repository.list_routes(routing_set.id))
        return tuple(self.resolve(version, lane) for lane in lane_ids)

    def conditional_guardrails_for_selection(
        self,
        version: int,
        lane: LaneId,
        selected_logical_ids: frozenset[str],
    ) -> tuple[ConditionalGuardrailPacket, ...]:
        """Return guardrails that must join a later selected-passage brief."""

        packet = self.resolve(version, lane).packet
        authorised_ids = {entry.logical_id for entry in packet.entries}
        unsupported = sorted(selected_logical_ids - authorised_ids)
        if unsupported:
            raise DocumentBRoutingError(
                f"Selected Document B logical IDs are not authorised for {lane}: "
                f"{', '.join(unsupported)}."
            )
        return tuple(
            rule
            for rule in packet.conditional_guardrails
            if selected_logical_ids.intersection(rule.trigger_logical_ids)
        )

    def _reference_asset(self, version: int) -> tuple[int, str]:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(DOCUMENT_B_KEY, version)
            return asset.id, asset.file_hash

    def _validate_version_unchanged(self, version: int, expected_id: int) -> None:
        if self._reference_asset(version)[0] != expected_id:
            raise DocumentBRoutingError(
                f"Document B version {version} changed during routing generation."
            )

    def _create_draft(
        self,
        reference_asset_id: int,
        config_version: str,
        config_sha256: str,
        document_b_file_sha256: str,
        catalog_sha256: str,
    ) -> int:
        with self.database.session() as session:
            created = DocumentBRoutingRepository(session).add_set(
                DocumentBRoutingSet(
                    reference_asset_id=reference_asset_id,
                    routing_config_version=config_version,
                    routing_config_sha256=config_sha256,
                    document_b_file_sha256=document_b_file_sha256,
                    extracted_section_catalog_sha256=catalog_sha256,
                    status=DocumentBRoutingSetStatus.DRAFT,
                    is_current=False,
                )
            )
            return created.id

    def _invalidate(self, routing_set_id: int, message: str) -> None:
        with self.database.session() as session:
            routing_set = DocumentBRoutingRepository(session).get_set(routing_set_id)
            if routing_set is not None:
                routing_set.status = DocumentBRoutingSetStatus.INVALID
                routing_set.validation_error = message[:2048]
                routing_set.is_current = False
                session.flush()

    def _persist_validated(
        self,
        routing_set_id: int,
        reference_asset_id: int,
        version: int,
        config: DocumentBRoutingConfig,
        packets: dict[LaneId, ResolvedLanePacket],
        catalog_sha256: str,
    ) -> RoutingSetSummary:
        with self.database.session() as session:
            repository = DocumentBRoutingRepository(session)
            routing_set = repository.get_set(routing_set_id)
            if routing_set is None:
                raise DocumentBRoutingError("The draft Document B routing set no longer exists.")
            routing_set.extracted_section_catalog_sha256 = catalog_sha256
            repository.add_routes(
                [
                    DocumentBLaneRoute(
                        routing_set_id=routing_set_id,
                        lane_id=lane,
                        ordered_route_json=packet.model_dump_json(),
                        secondary_lane_constraints_json=_constraint_packet(
                            config.lanes[lane]
                        ).model_dump_json(),
                    )
                    for lane, packet in packets.items()
                ]
            )
            repository.supersede_current(reference_asset_id)
            routing_set.status = DocumentBRoutingSetStatus.VALIDATED
            routing_set.validation_error = None
            routing_set.is_current = True
            session.flush()
            return _summary(routing_set, version)


def _compile_packets(
    config: DocumentBRoutingConfig,
    sections: tuple[DocumentBSectionRecord, ...],
) -> dict[LaneId, ResolvedLanePacket]:
    by_path = _sections_by_heading_path(sections)
    _validate_referenced_paths(config, by_path)
    packets: dict[LaneId, ResolvedLanePacket] = {}
    for lane, route in config.lanes.items():
        specifications = _route_specifications(config, route)
        entries: list[ResolvedRouteEntry] = []
        used_roots: set[str] = set()
        expanded_owner: dict[str, str] = {}
        for logical_id, role, inclusion, delivery_mode in specifications:
            if logical_id in used_roots:
                raise DocumentBRoutingError(
                    f"{lane} configures logical section '{logical_id}' more than once."
                )
            used_roots.add(logical_id)
            catalog = config.section_catalog[logical_id]
            root = by_path.get(_normalized_path(catalog.heading_path))
            if root is None:
                raise DocumentBRoutingError(
                    f"{lane} cannot resolve exact heading path "
                    f"'{' > '.join(catalog.heading_path)}' for '{logical_id}'."
                )
            tree = _section_tree(sections, root) if catalog.include_descendants else (root,)
            expanded_ids = tuple(section.section_id for section in tree)
            for section_id in expanded_ids:
                previous = expanded_owner.get(section_id)
                if previous is not None:
                    raise DocumentBRoutingError(
                        f"{lane} has overlapping configured roots '{previous}' and "
                        f"'{logical_id}' at section '{section_id}'."
                    )
                expanded_owner[section_id] = logical_id
            entries.append(
                ResolvedRouteEntry(
                    logical_id=logical_id,
                    section_id=root.section_id,
                    heading=root.heading_title,
                    heading_path=catalog.heading_path,
                    role=role,
                    inclusion=inclusion,
                    delivery_mode=delivery_mode,
                    include_descendants=catalog.include_descendants,
                    expanded_section_ids=expanded_ids,
                )
            )
        conditional_guardrails = _conditional_guardrails(
            config,
            set(entry.logical_id for entry in entries),
            by_path,
        )
        packets[lane] = ResolvedLanePacket(
            lane=lane,
            entries=tuple(entries),
            conditional_guardrails=conditional_guardrails,
        )
    return packets


def _validate_referenced_paths(
    config: DocumentBRoutingConfig,
    by_path: dict[tuple[str, ...], DocumentBSectionRecord],
) -> None:
    """Require every logical ID used by any route to exist in this Document B version."""

    for logical_id in sorted(referenced_logical_section_ids(config)):
        catalog = config.section_catalog[logical_id]
        if _normalized_path(catalog.heading_path) not in by_path:
            raise DocumentBRoutingError(
                f"Document B cannot resolve exact heading path "
                f"'{' > '.join(catalog.heading_path)}' for '{logical_id}'."
            )


def _sections_by_heading_path(
    sections: tuple[DocumentBSectionRecord, ...],
) -> dict[tuple[str, ...], DocumentBSectionRecord]:
    result: dict[tuple[str, ...], DocumentBSectionRecord] = {}
    stack: list[DocumentBSectionRecord] = []
    for section in sections:
        if section.heading_level == 0:
            continue
        while stack and stack[-1].heading_level >= section.heading_level:
            stack.pop()
        stack.append(section)
        path = tuple(_normalize_heading(item.heading_title) for item in stack)
        if path in result:
            raise DocumentBRoutingError(
                f"Document B contains duplicate exact heading path '{' > '.join(path)}'."
            )
        result[path] = section
    return result


def _section_tree(
    sections: tuple[DocumentBSectionRecord, ...],
    root: DocumentBSectionRecord,
) -> tuple[DocumentBSectionRecord, ...]:
    start = sections.index(root)
    tree: list[DocumentBSectionRecord] = []
    for section in sections[start:]:
        if tree and section.heading_level <= root.heading_level:
            break
        tree.append(section)
    return tuple(tree)


def _route_specifications(
    config: DocumentBRoutingConfig,
    lane: LaneRouteConfig,
) -> tuple[tuple[str, DocumentBRouteRole, RouteInclusion, RouteDeliveryMode], ...]:
    mandatory = RouteInclusion.MANDATORY
    optional = RouteInclusion.OPTIONAL
    shared = config.shared_route
    values: list[tuple[str, DocumentBRouteRole, RouteInclusion, RouteDeliveryMode]] = []

    def add(
        logical_ids: tuple[str, ...],
        role: DocumentBRouteRole,
        inclusion: RouteInclusion,
        delivery_mode: RouteDeliveryMode,
    ) -> None:
        values.extend((logical_id, role, inclusion, delivery_mode) for logical_id in logical_ids)

    direct = RouteDeliveryMode.DIRECT_CONTEXT
    required_scope = RouteDeliveryMode.VECTOR_SCOPE_REQUIRED
    optional_scope = RouteDeliveryMode.VECTOR_SCOPE_OPTIONAL
    add(shared.mandatory_workflow, DocumentBRouteRole.WORKFLOW, mandatory, direct)
    add(lane.summary, DocumentBRouteRole.SUMMARY, mandatory, direct)
    add(lane.experience_framing, DocumentBRouteRole.EXPERIENCE_FRAMING, mandatory, direct)
    add(lane.positioning_playbook, DocumentBRouteRole.POSITIONING_PLAYBOOK, mandatory, direct)
    add(
        lane.mandatory_bullet_libraries,
        DocumentBRouteRole.BULLET_LIBRARY,
        mandatory,
        required_scope,
    )
    add(lane.optional_bullet_libraries, DocumentBRouteRole.BULLET_LIBRARY, optional, optional_scope)
    add(shared.mandatory_skills, DocumentBRouteRole.SKILLS, mandatory, direct)
    add(lane.additional_skills, DocumentBRouteRole.SKILLS, mandatory, direct)
    add(
        shared.mandatory_assembly_and_guardrails,
        DocumentBRouteRole.GUARDRAIL,
        mandatory,
        direct,
    )
    add(lane.additional_guardrails, DocumentBRouteRole.GUARDRAIL, mandatory, direct)
    add(shared.phase_2_templates, DocumentBRouteRole.PHASE_2_BRIEF_TEMPLATE, mandatory, direct)
    add(shared.phase_3_templates, DocumentBRouteRole.PHASE_3_CV_TEMPLATE, mandatory, direct)
    add(
        lane.secondary_lane_constraints.supporting_sections,
        DocumentBRouteRole.SUPPORTING_EXPERIENCE,
        optional,
        direct,
    )
    return tuple(values)


def _constraint_packet(route: LaneRouteConfig) -> SecondaryLaneConstraintPacket:
    constraints = route.secondary_lane_constraints
    return SecondaryLaneConstraintPacket(
        default_disposition_for_unlisted_lane=constraints.default_disposition_for_unlisted_lane,
        source_sections=constraints.source_section,
        allowed=constraints.allowed,
        cautious=tuple({"lane": item.lane, "reason": item.reason} for item in constraints.cautious),
    )


def _conditional_guardrails(
    config: DocumentBRoutingConfig,
    included_logical_ids: set[str],
    by_path: dict[tuple[str, ...], DocumentBSectionRecord],
) -> tuple[ConditionalGuardrailPacket, ...]:
    rules: list[ConditionalGuardrailPacket] = []
    for rule in config.conditional_guardrails:
        if not included_logical_ids.intersection(rule.trigger_sections):
            continue
        required_section_ids: list[str] = []
        for logical_id in rule.required_sections:
            catalog = config.section_catalog[logical_id]
            section = by_path.get(_normalized_path(catalog.heading_path))
            if section is None:
                raise DocumentBRoutingError(
                    f"Conditional guardrail cannot resolve exact heading path "
                    f"'{' > '.join(catalog.heading_path)}' for '{logical_id}'."
                )
            required_section_ids.append(section.section_id)
        rules.append(
            ConditionalGuardrailPacket(
                trigger_logical_ids=rule.trigger_sections,
                required_logical_ids=rule.required_sections,
                required_section_ids=tuple(required_section_ids),
            )
        )
    return tuple(rules)


def _normalized_path(path: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_normalize_heading(item) for item in path)


def _normalize_heading(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    return " ".join(normalized.strip().split())


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _catalog_hash(sections: tuple[DocumentBSectionRecord, ...]) -> str:
    serialized = json.dumps(
        [
            {
                "section_id": section.section_id,
                "heading_number": section.heading_number,
                "heading_title": section.heading_title,
                "heading_level": section.heading_level,
                "sequence": section.sequence,
                "section_text": section.section_text,
            }
            for section in sections
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(serialized)


def _summary(routing_set: DocumentBRoutingSet, version: int) -> RoutingSetSummary:
    return RoutingSetSummary(
        routing_set_id=routing_set.id,
        document_b_version=version,
        routing_config_version=routing_set.routing_config_version,
        routing_config_sha256=routing_set.routing_config_sha256,
        document_b_file_sha256=routing_set.document_b_file_sha256,
        extracted_section_catalog_sha256=routing_set.extracted_section_catalog_sha256,
        status=routing_set.status,
        is_current=routing_set.is_current,
    )
