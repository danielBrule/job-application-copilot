"""Compose authorised, cache-aware context for English CV-generation stages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    AssessmentStatus,
    CvGenerationBriefOutput,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
    RouteDeliveryMode,
    RouteInclusion,
)
from job_application_copilot.errors import ApplicationOperationError
from job_application_copilot.repositories import (
    AssessmentRepository,
    Database,
    JobRepository,
    PromptDefinitionRepository,
    ReferenceAssetRepository,
)
from job_application_copilot.services.document_b_retrieval import DocumentBRetrievalPacket
from job_application_copilot.services.document_b_routing import (
    DocumentBRoutingManifestService,
    ResolvedRouting,
)
from job_application_copilot.services.document_b_sections import DocumentBSectionService
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFilePathError,
    resolve_path_within,
    sha256_file_hash,
)

CV_GENERATION_PIPELINE_GROUP = "generation/english"
CV_CONTEXT_CACHE_IDENTITY_VERSION = 1


class CvGenerationContextError(ApplicationOperationError):
    """Raised when a CV stage cannot be given an authorised reproducible packet."""


class CvGenerationTextInput(BaseModel):
    """One ordered text part in a provider-neutral CV-generation request."""

    model_config = ConfigDict(frozen=True)

    type: Literal["input_text"] = "input_text"
    section: str
    text: str
    cache_boundary: bool = False


class CvGenerationBriefInput(BaseModel):
    """The retained stage-one handover required by later generation stages."""

    model_config = ConfigDict(frozen=True)

    document_a_version: int = Field(gt=0)
    document_b_version: int = Field(gt=0)
    routing_set_id: int = Field(gt=0)
    output: CvGenerationBriefOutput

    @property
    def selected_section_ids(self) -> frozenset[str]:
        return self.output.selected_section_ids

    @property
    def selected_passage_ids(self) -> frozenset[str]:
        return self.output.selected_passage_ids

    @property
    def guardrail_ids(self) -> frozenset[str]:
        return self.output.guardrail_ids


class CvGenerationTraceability(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: int
    model_identifier: str
    document_a_version: int
    document_b_version: int
    document_b_hash: str
    routing_set_id: int
    routing_config_version: str
    routing_config_hash: str
    prompt_asset_key: str
    prompt_version: int
    prompt_hash: str
    schema_hash: str


class CvGenerationCacheIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity_version: int
    identity_hash: str
    stage: int
    model_identifier: str
    primary_lane: str


class CvGenerationContext(BaseModel):
    """An inspectable stable prefix plus job-specific CV-generation material."""

    model_config = ConfigDict(frozen=True)

    input: tuple[CvGenerationTextInput, ...]
    stable_prefix_item_count: int
    cache_boundary_index: int
    traceability: CvGenerationTraceability
    cache_identity: CvGenerationCacheIdentity
    secondary_lane: str | None

    @property
    def stable_prefix(self) -> tuple[CvGenerationTextInput, ...]:
        return self.input[: self.stable_prefix_item_count]

    @property
    def job_content(self) -> tuple[CvGenerationTextInput, ...]:
        return self.input[self.cache_boundary_index + 1 :]


@dataclass(frozen=True, slots=True)
class _PromptInput:
    asset_key: str
    version: int
    file_hash: str
    text: str


class CvGenerationContextBuilder:
    """Build stage packets without invoking OpenAI or persisting a CV brief."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings
        self.sections = DocumentBSectionService(database, settings)
        self.routing = DocumentBRoutingManifestService(database, self.sections)

    def build(
        self,
        job_id: int,
        *,
        stage: int,
        model_identifier: str,
        response_schema: dict[str, Any],
        retrieval: DocumentBRetrievalPacket | None = None,
        brief: CvGenerationBriefInput | None = None,
        prior_stage_output: str | None = None,
        template_contract: str | None = None,
    ) -> CvGenerationContext:
        """Return an authorised packet for one configured English generation stage."""

        if stage < 1:
            raise CvGenerationContextError("CV-generation stage must be positive.")
        model = model_identifier.strip()
        if not model:
            raise CvGenerationContextError("A CV-generation model identifier is required.")
        prompt = self._prompt(stage)
        job, assessment = self._job_and_assessment(job_id)
        lane = assessment.selected_cv_lane
        if lane is None:
            raise CvGenerationContextError("A confirmed primary CV lane is required.")
        document_b_version, document_b_hash = self._active_document_b()
        primary = self.routing.resolve(document_b_version, lane)
        secondary = _authorised_secondary(primary, assessment.secondary_role_family)
        passages = () if retrieval is None else retrieval.passages
        self._validate_retrieval(primary, document_b_version, passages)
        if stage > 1:
            self._validate_brief(
                brief,
                primary,
                assessment.document_a_version or 0,
                document_b_version,
                passages,
            )
        elif brief is not None:
            raise CvGenerationContextError(
                "Only later CV-generation stages may receive a CV-generation brief."
            )
        if prior_stage_output is not None and not prior_stage_output.strip():
            raise CvGenerationContextError("Prior-stage output cannot be blank when supplied.")

        schema_text = _canonical_json(response_schema)
        schema_hash = _sha256(schema_text.encode("utf-8"))
        mandatory_text = self._mandatory_document_b_text(
            primary,
            document_b_version,
            selected_section_ids=None if brief is None else brief.selected_section_ids,
            guardrail_ids=frozenset() if brief is None else brief.guardrail_ids,
        )
        primary_text = _canonical_json(
            {
                "primary_lane": lane,
                "instruction": "Use this as the dominant role-family narrative. It controls the summary, experience framing and core Document B material.",
            }
        )
        traceability = CvGenerationTraceability(
            stage=stage,
            model_identifier=model,
            document_a_version=assessment.document_a_version or 0,
            document_b_version=document_b_version,
            document_b_hash=document_b_hash,
            routing_set_id=primary.summary.routing_set_id,
            routing_config_version=primary.summary.routing_config_version,
            routing_config_hash=primary.summary.routing_config_sha256,
            prompt_asset_key=prompt.asset_key,
            prompt_version=prompt.version,
            prompt_hash=prompt.file_hash,
            schema_hash=schema_hash,
        )
        if traceability.document_a_version <= 0:
            raise CvGenerationContextError("The stored assessment has no Document A version.")
        cache_identity = _cache_identity(traceability, lane)
        variable_items = self._variable_items(
            job_description=job.job_description,
            assessment=assessment,
            secondary=secondary,
            passages=passages,
            brief=brief,
            prior_stage_output=prior_stage_output,
            template_contract=template_contract,
        )
        stable = (
            CvGenerationTextInput(section="stage_instructions", text=prompt.text),
            CvGenerationTextInput(section="primary_lane", text=primary_text),
            CvGenerationTextInput(section="mandatory_document_b", text=mandatory_text),
        )
        boundary = CvGenerationTextInput(section="cache_boundary", text="", cache_boundary=True)
        return CvGenerationContext(
            input=stable + (boundary,) + variable_items,
            stable_prefix_item_count=len(stable),
            cache_boundary_index=len(stable),
            traceability=traceability,
            cache_identity=cache_identity,
            secondary_lane=secondary,
        )

    def _job_and_assessment(self, job_id: int) -> tuple[Any, Any]:
        with self.database.session() as session:
            job = JobRepository(session).require(job_id)
            assessment = AssessmentRepository(session).require_for_job(job_id)
            if assessment.status is not AssessmentStatus.ASSESSED:
                raise CvGenerationContextError("CV generation requires a completed assessment.")
            if AssessmentRepository.is_stale(assessment, job):
                raise CvGenerationContextError("CV generation requires a current assessment.")
            return job, assessment

    def _active_document_b(self) -> tuple[int, str]:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).get_active(DOCUMENT_B_KEY)
            if asset is None or asset.processing_status is not ReferenceAssetProcessingStatus.READY:
                raise CvGenerationContextError("An active READY Document B is required.")
            return asset.version, asset.file_hash

    def _prompt(self, stage: int) -> _PromptInput:
        with self.database.session() as session:
            definitions = [
                definition
                for definition in PromptDefinitionRepository(session).list(enabled_only=True)
                if definition.pipeline_group == CV_GENERATION_PIPELINE_GROUP
                and definition.position == stage
            ]
            if len(definitions) != 1:
                raise CvGenerationContextError(
                    f"CV-generation stage {stage} requires exactly one enabled English prompt."
                )
            definition = definitions[0]
            asset = ReferenceAssetRepository(session).get_active(definition.asset_key)
            if asset is None or asset.asset_type is not ReferenceAssetType.PROMPT:
                raise CvGenerationContextError(
                    f"CV-generation prompt '{definition.asset_key}' is unavailable."
                )
            if asset.processing_status is not ReferenceAssetProcessingStatus.READY:
                raise CvGenerationContextError(
                    f"CV-generation prompt '{definition.asset_key}' is not READY."
                )
            asset_key, version, file_hash, relative_path = (
                asset.asset_key,
                asset.version,
                asset.file_hash,
                asset.file_path,
            )
        try:
            path = resolve_path_within(
                self.settings.prompts_folder, self.settings.reference_folder / relative_path
            )
            content = path.read_bytes()
            text = content.decode("utf-8")
        except (ImmutableFilePathError, OSError, UnicodeError) as error:
            raise CvGenerationContextError(
                f"CV-generation prompt '{asset_key}' cannot be read safely."
            ) from error
        if not text.strip() or sha256_file_hash(content) != file_hash:
            raise CvGenerationContextError(
                f"CV-generation prompt '{asset_key}' failed integrity validation."
            )
        return _PromptInput(asset_key, version, file_hash, text)

    def _mandatory_document_b_text(
        self,
        routing: ResolvedRouting,
        version: int,
        *,
        selected_section_ids: frozenset[str] | None,
        guardrail_ids: frozenset[str],
    ) -> str:
        sections: list[dict[str, object]] = []
        included: set[str] = set()
        for entry in routing.packet.entries:
            if (
                entry.delivery_mode is not RouteDeliveryMode.DIRECT_CONTEXT
                or entry.inclusion is not RouteInclusion.MANDATORY
            ):
                continue
            for section_id in entry.expanded_section_ids:
                if (
                    selected_section_ids is not None
                    and section_id not in selected_section_ids
                    and entry.logical_id not in guardrail_ids
                ):
                    continue
                if section_id in included:
                    continue
                included.add(section_id)
                section = self.sections.require_section(version, section_id)
                sections.append(
                    {
                        "logical_id": entry.logical_id,
                        "role": entry.role,
                        "section_id": section.section_id,
                        "text": section.section_text,
                    }
                )
        return _canonical_json(sections)

    @staticmethod
    def _validate_retrieval(
        routing: ResolvedRouting, version: int, passages: tuple[Any, ...]
    ) -> None:
        authorised = {
            section_id
            for entry in routing.packet.entries
            if entry.delivery_mode
            in (RouteDeliveryMode.VECTOR_SCOPE_REQUIRED, RouteDeliveryMode.VECTOR_SCOPE_OPTIONAL)
            for section_id in entry.expanded_section_ids
        }
        for passage in passages:
            if passage.document_b_version != version or passage.section_id not in authorised:
                raise CvGenerationContextError(
                    "Supplementary passage is not authorised by the primary lane route."
                )

    @staticmethod
    def _validate_brief(
        brief: CvGenerationBriefInput | None,
        routing: ResolvedRouting,
        document_a_version: int,
        version: int,
        passages: tuple[Any, ...],
    ) -> None:
        if brief is None:
            raise CvGenerationContextError(
                "Later CV-generation stages require a retained CV-generation brief."
            )
        if brief.document_a_version != document_a_version:
            raise CvGenerationContextError(
                "CV-generation brief does not match the current Document A assessment."
            )
        if (
            brief.document_b_version != version
            or brief.routing_set_id != routing.summary.routing_set_id
        ):
            raise CvGenerationContextError(
                "CV-generation brief does not match the current authorised route."
            )
        available_sections = {
            section_id
            for entry in routing.packet.entries
            if (
                entry.delivery_mode is RouteDeliveryMode.DIRECT_CONTEXT
                and entry.inclusion is RouteInclusion.MANDATORY
            )
            for section_id in entry.expanded_section_ids
        }
        if not brief.selected_section_ids.issubset(available_sections):
            raise CvGenerationContextError(
                "CV-generation brief contains unauthorised Document B sections."
            )
        if not brief.selected_passage_ids.issuperset(passage.passage_id for passage in passages):
            raise CvGenerationContextError(
                "Supplementary passages are not recorded in the CV-generation brief."
            )

    @staticmethod
    def _variable_items(
        *,
        job_description: str,
        assessment: Any,
        secondary: str | None,
        passages: tuple[Any, ...],
        brief: CvGenerationBriefInput | None,
        prior_stage_output: str | None,
        template_contract: str | None,
    ) -> tuple[CvGenerationTextInput, ...]:
        values = [
            CvGenerationTextInput(
                section="assessment",
                text=_canonical_json(
                    {
                        "primary_role_family": assessment.primary_role_family,
                        "secondary_role_family": assessment.secondary_role_family,
                        "secondary_cv_angle": assessment.secondary_cv_angle,
                        "evidence_anchors": assessment.evidence_anchors,
                        "evidence_gaps": assessment.evidence_gaps,
                        "strong_fit_signals": assessment.strong_fit_signals,
                        "overclaiming_risks": assessment.overclaiming_risks,
                    }
                ),
            ),
            CvGenerationTextInput(section="job_description", text=job_description),
        ]
        if secondary is not None:
            values.insert(
                0,
                CvGenerationTextInput(
                    section="secondary_lane",
                    text=_canonical_json(
                        {
                            "secondary_lane": secondary,
                            "instruction": "This is supporting context only. Do not replace the primary lane, headline, summary or core employer framing.",
                        }
                    ),
                ),
            )
        if passages:
            values.insert(
                -1,
                CvGenerationTextInput(
                    section="supplementary_passages",
                    text=_canonical_json([passage.model_dump() for passage in passages]),
                ),
            )
        if brief is not None:
            values.append(
                CvGenerationTextInput(section="cv_generation_brief", text=brief.model_dump_json())
            )
        if prior_stage_output is not None:
            values.append(
                CvGenerationTextInput(section="prior_stage_output", text=prior_stage_output)
            )
        if template_contract is not None:
            values.append(CvGenerationTextInput(section="template_contract", text=template_contract))
        return tuple(values)


def _authorised_secondary(routing: ResolvedRouting, suggested: str | None) -> str | None:
    if suggested is None or suggested == routing.packet.lane:
        return None
    if suggested in routing.constraints.allowed:
        return suggested
    if any(item["lane"] == suggested for item in routing.constraints.cautious):
        return suggested
    return None


def _cache_identity(
    traceability: CvGenerationTraceability, primary_lane: str
) -> CvGenerationCacheIdentity:
    components = {
        "identity_version": CV_CONTEXT_CACHE_IDENTITY_VERSION,
        "stage": traceability.stage,
        "model_identifier": traceability.model_identifier,
        "primary_lane": primary_lane,
        "document_b_version": traceability.document_b_version,
        "document_b_hash": traceability.document_b_hash,
        "routing_config_version": traceability.routing_config_version,
        "routing_config_hash": traceability.routing_config_hash,
        "prompt_version": traceability.prompt_version,
        "prompt_hash": traceability.prompt_hash,
        "schema_hash": traceability.schema_hash,
    }
    return CvGenerationCacheIdentity(
        identity_version=CV_CONTEXT_CACHE_IDENTITY_VERSION,
        identity_hash=hashlib.sha256(_canonical_json(components).encode("utf-8")).hexdigest(),
        stage=traceability.stage,
        model_identifier=traceability.model_identifier,
        primary_lane=primary_lane,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()
