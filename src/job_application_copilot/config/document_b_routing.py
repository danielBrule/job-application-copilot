"""Validated canonical configuration for deterministic Document B routing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from job_application_copilot.domain import LaneId, MandateSupportCategory


class RoutingConfigError(ValueError):
    """Raised when the private routing configuration is missing or invalid."""


class ConfigModel(BaseModel):
    """Reject unknown YAML fields so every retained setting has runtime meaning."""

    model_config = ConfigDict(extra="forbid")


class NormalizationConfig(ConfigModel):
    unicode_form: Literal["NFKC"]
    trim_outer_whitespace: Literal[True]
    collapse_internal_whitespace: Literal[True]
    normalize_non_breaking_spaces: Literal[True]
    normalize_punctuation: Literal[False]


class ResolutionConfig(ConfigModel):
    strategy: Literal["EXACT_HEADING_PATH_AFTER_NORMALIZATION"]
    normalization: NormalizationConfig
    case_sensitive: Literal[True]
    allow_fuzzy_matching: Literal[False]
    allow_substring_matching: Literal[False]
    allow_model_resolution: Literal[False]
    toc_hints_are_identifiers: Literal[False]
    reject_overlap_when_ancestor_expands: Literal[True]
    allow_parent_and_child_when_parent_excludes_descendants: Literal[True]
    deduplicate_expanded_sections: Literal[True]
    preserve_first_configured_sequence: Literal[True]
    fail_on_missing_mandatory_section: Literal[True]


class SectionCatalogEntry(ConfigModel):
    toc_hint: str | float | int
    heading_path: tuple[str, ...] = Field(min_length=1)
    include_descendants: bool


class SharedRouteConfig(ConfigModel):
    mandatory_workflow: tuple[str, ...]
    mandatory_skills: tuple[str, ...]
    mandatory_assembly_and_guardrails: tuple[str, ...]
    phase_2_templates: tuple[str, ...]
    phase_3_templates: tuple[str, ...]


class CautiousLaneConfig(ConfigModel):
    lane: LaneId
    reason: str = Field(min_length=1)


class SecondaryLaneConstraintsConfig(ConfigModel):
    default_disposition_for_unlisted_lane: Literal["EXCLUDED"]
    source_section: tuple[str, ...] = Field(min_length=1)
    allowed: tuple[LaneId, ...]
    cautious: tuple[CautiousLaneConfig, ...]
    supporting_sections: tuple[str, ...]


class LaneRouteConfig(ConfigModel):
    status: Literal["SUPPORTED"]
    summary: tuple[str, ...]
    experience_framing: tuple[str, ...]
    positioning_playbook: tuple[str, ...]
    mandatory_bullet_libraries: tuple[str, ...]
    optional_bullet_libraries: tuple[str, ...]
    additional_skills: tuple[str, ...]
    additional_guardrails: tuple[str, ...]
    secondary_lane_constraints: SecondaryLaneConstraintsConfig


class SupportingRouteConfig(ConfigModel):
    category: Literal["INCOMPLETE_PRIMARY_LANE", "OPTIONAL_SUPPORTING_CONTENT"]
    primary_lane_selectable: Literal[False]
    secondary_support_selectable: Literal[True]
    reason: str | None = None
    available_sections: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()


class ConditionalGuardrailConfig(ConfigModel):
    trigger_sections: tuple[str, ...] = Field(min_length=1)
    required_sections: tuple[str, ...]


class MandateSupportCategoryConfig(ConfigModel):
    """Narrow Document B material available for one controlled mandate category."""

    sections: tuple[str, ...] = Field(min_length=1)


class DocumentBRoutingConfig(ConfigModel):
    schema_version: Literal[1]
    routing_config_version: str = Field(min_length=1)
    resolution: ResolutionConfig
    section_catalog: dict[str, SectionCatalogEntry]
    conditional_guardrails: tuple[ConditionalGuardrailConfig, ...]
    mandate_support_categories: dict[MandateSupportCategory, MandateSupportCategoryConfig]
    shared_route: SharedRouteConfig
    lanes: dict[LaneId, LaneRouteConfig]
    supporting_routes: dict[str, SupportingRouteConfig]

    @model_validator(mode="after")
    def validate_completeness(self) -> DocumentBRoutingConfig:
        if not self.lanes:
            raise ValueError("lane catalogue must contain at least one supported lane")
        configured_lanes = set(self.lanes)
        unresolved = sorted(referenced_logical_section_ids(self) - set(self.section_catalog))
        if unresolved:
            raise ValueError(f"unknown logical section references: {', '.join(unresolved)}")
        for lane, route in self.lanes.items():
            counts = (
                len(route.summary),
                len(route.experience_framing),
                len(route.positioning_playbook),
            )
            if counts != (1, 1, 1):
                raise ValueError(
                    f"{lane} must configure exactly one summary, experience framing, "
                    "and positioning playbook"
                )
            if not route.mandatory_bullet_libraries:
                raise ValueError(f"{lane} has no mandatory bullet library")
            secondary_lanes = set(route.secondary_lane_constraints.allowed)
            secondary_lanes.update(
                cautious.lane for cautious in route.secondary_lane_constraints.cautious
            )
            unknown_secondary = sorted(secondary_lanes - configured_lanes)
            if unknown_secondary:
                raise ValueError(
                    f"{lane} references unconfigured secondary lanes: "
                    f"{', '.join(unknown_secondary)}"
                )
        if len(self.shared_route.phase_2_templates) != 1:
            raise ValueError("shared route must configure exactly one Phase 2 template")
        if len(self.shared_route.phase_3_templates) != 1:
            raise ValueError("shared route must configure exactly one Phase 3 template")
        return self


def load_document_b_routing_config(path: Path) -> DocumentBRoutingConfig:
    """Load and validate one installation's private UTF-8 YAML."""

    try:
        return parse_document_b_routing_config(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RoutingConfigError(
            "Document B routing configuration is missing at "
            f"'{path}'. Copy 'templates/document-b-lane-routes.template.yaml' to this "
            "private path and customise it for the active Document B."
        ) from error
    except (OSError, RoutingConfigError) as error:
        raise RoutingConfigError(
            f"Document B routing configuration at '{path}' is invalid: {error}"
        ) from error


def parse_document_b_routing_config(content: str) -> DocumentBRoutingConfig:
    """Parse and validate private routing YAML supplied by an editor or file."""

    try:
        raw: Any = yaml.safe_load(content)
        return DocumentBRoutingConfig.model_validate(raw)
    except (yaml.YAMLError, ValueError) as error:
        raise RoutingConfigError(f"Document B routing configuration is invalid: {error}") from error


def referenced_logical_section_ids(config: DocumentBRoutingConfig) -> set[str]:
    shared = config.shared_route
    references = set(
        shared.mandatory_workflow
        + shared.mandatory_skills
        + shared.mandatory_assembly_and_guardrails
        + shared.phase_2_templates
        + shared.phase_3_templates
    )
    for route in config.lanes.values():
        references.update(route.summary)
        references.update(route.experience_framing)
        references.update(route.positioning_playbook)
        references.update(route.mandatory_bullet_libraries)
        references.update(route.optional_bullet_libraries)
        references.update(route.additional_skills)
        references.update(route.additional_guardrails)
        references.update(route.secondary_lane_constraints.source_section)
        references.update(route.secondary_lane_constraints.supporting_sections)
    for rule in config.conditional_guardrails:
        references.update(rule.trigger_sections)
        references.update(rule.required_sections)
    for support in config.mandate_support_categories.values():
        references.update(support.sections)
    for supporting_route in config.supporting_routes.values():
        references.update(supporting_route.available_sections)
        references.update(supporting_route.sections)
    return references
