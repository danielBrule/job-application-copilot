"""Compose the complete, ordered, evidence-grounded assessment context."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from job_application_copilot.config import AppSettings, AssessmentReasoningEffort
from job_application_copilot.domain import (
    ASSESSMENT_SCHEMA_VERSION,
    DOCUMENT_B_KEY,
    DocumentBRoutingSetStatus,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
    assessment_output_json_schema,
)
from job_application_copilot.errors import ApplicationOperationError
from job_application_copilot.repositories import (
    Database,
    DocumentBRoutingRepository,
    JobRepository,
    PromptDefinitionRepository,
    ReferenceAssetRepository,
)
from job_application_copilot.services.document_a_input import (
    DocumentAInput,
    DocumentAInputService,
    DocumentAInputUnavailableError,
)
from job_application_copilot.services.immutable_file_storage import (
    ImmutableFilePathError,
    resolve_path_within,
    sha256_file_hash,
)

ASSESSMENT_PIPELINE_GROUP = "assessment"
ASSESSMENT_PIPELINE_STEP = "ASSESSMENT"
ASSESSMENT_CACHE_IDENTITY_VERSION = 1
STABLE_PREFIX_ITEM_COUNT = 3


class AssessmentContextError(ApplicationOperationError):
    """Raised when an authorised assessment context cannot be assembled."""


class AssessmentTextInput(BaseModel):
    """One ordered text part in the provider-neutral assessment input."""

    model_config = ConfigDict(frozen=True)

    type: Literal["input_text"] = "input_text"
    section: Literal[
        "assessment_instructions",
        "response_schema",
        "job_metadata",
        "job_description",
    ]
    text: str


class AssessmentFileInput(BaseModel):
    """One complete uploaded-file part in the provider-neutral assessment input."""

    model_config = ConfigDict(frozen=True)

    type: Literal["input_file"] = "input_file"
    section: Literal["document_a"] = "document_a"
    file_id: str


AssessmentInput = AssessmentTextInput | AssessmentFileInput


class AssessmentTraceability(BaseModel):
    """Versions and identifiers required to reproduce one assessment context."""

    model_config = ConfigDict(frozen=True)

    document_a_reference_asset_id: int
    document_a_version: int
    document_a_hash: str
    prompt_asset_key: str
    prompt_version: int
    prompt_hash: str
    schema_version: int
    schema_hash: str
    model_identifier: str
    reasoning_effort: AssessmentReasoningEffort
    routing_set_id: int
    routing_config_version: str


class AssessmentCacheIdentity(BaseModel):
    """Privacy-safe cache identity derived without private source content."""

    model_config = ConfigDict(frozen=True)

    identity_version: int
    identity_hash: str
    operation: Literal["ASSESSMENT"]
    pipeline_step: Literal["ASSESSMENT"]
    model_identifier: str
    document_a_version: int
    document_a_hash: str
    prompt_asset_key: str
    prompt_version: int
    prompt_hash: str
    schema_version: int
    schema_hash: str


class AssessmentContext(BaseModel):
    """Complete rendered assessment request plus local-only metadata."""

    model_config = ConfigDict(frozen=True)

    input: tuple[AssessmentInput, ...]
    stable_prefix_item_count: int
    reasoning_effort: AssessmentReasoningEffort
    response_schema: dict[str, Any]
    traceability: AssessmentTraceability
    cache_identity: AssessmentCacheIdentity

    @property
    def stable_prefix(self) -> tuple[AssessmentInput, ...]:
        """Return the exact reusable prefix before variable job content."""

        return self.input[: self.stable_prefix_item_count]

    @property
    def job_content(self) -> tuple[AssessmentInput, ...]:
        """Return the variable job-specific suffix."""

        return self.input[self.stable_prefix_item_count :]

    def rendered_json(self) -> str:
        """Render an inspectable JSON request without making a model call."""

        return self.model_dump_json(indent=2)


@dataclass(frozen=True, slots=True)
class _PromptInput:
    asset_key: str
    version: int
    file_hash: str
    text: str


@dataclass(frozen=True, slots=True)
class _RoutingInput:
    routing_set_id: int
    routing_config_version: str
    allowed_lane_ids: tuple[str, ...]


class AssessmentContextBuilder:
    """Build a deterministic prefix followed by exact variable job content."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings

    def build(
        self,
        job_id: int,
        *,
        model_identifier: str | None = None,
        reasoning_effort: AssessmentReasoningEffort | None = None,
    ) -> AssessmentContext:
        """Assemble all authorised assessment inputs without contacting OpenAI."""

        model = self._resolve_model_identifier(model_identifier)
        effort = reasoning_effort or self.settings.assessment_reasoning_effort
        document_a = self._document_a()
        prompt = self._assessment_prompt()
        routing = self._routing()
        schema = assessment_output_json_schema(routing.allowed_lane_ids)
        canonical_schema = _canonical_json(schema)
        schema_hash = _sha256_text(canonical_schema)

        with self.database.session() as session:
            job = JobRepository(session).require(job_id)
            job_metadata = _canonical_json(
                {
                    "company": job.company,
                    "job_title": job.job_title,
                    "language": job.language.value,
                    "location": job.location.value,
                }
            )
            job_description = job.job_description

        traceability = AssessmentTraceability(
            document_a_reference_asset_id=document_a.reference_asset_id,
            document_a_version=document_a.version,
            document_a_hash=document_a.file_hash,
            prompt_asset_key=prompt.asset_key,
            prompt_version=prompt.version,
            prompt_hash=prompt.file_hash,
            schema_version=ASSESSMENT_SCHEMA_VERSION,
            schema_hash=schema_hash,
            model_identifier=model,
            reasoning_effort=effort,
            routing_set_id=routing.routing_set_id,
            routing_config_version=routing.routing_config_version,
        )
        cache_identity = _cache_identity(traceability)
        return AssessmentContext(
            input=(
                AssessmentTextInput(
                    section="assessment_instructions",
                    text=prompt.text,
                ),
                AssessmentTextInput(
                    section="response_schema",
                    text=canonical_schema,
                ),
                AssessmentFileInput(file_id=document_a.openai_file_id),
                AssessmentTextInput(
                    section="job_metadata",
                    text=job_metadata,
                ),
                AssessmentTextInput(
                    section="job_description",
                    text=job_description,
                ),
            ),
            stable_prefix_item_count=STABLE_PREFIX_ITEM_COUNT,
            reasoning_effort=effort,
            response_schema=schema,
            traceability=traceability,
            cache_identity=cache_identity,
        )

    def _resolve_model_identifier(self, explicit_model: str | None) -> str:
        model = explicit_model if explicit_model is not None else self.settings.assessment_model
        if model is None or not model.strip():
            raise AssessmentContextError(
                "No assessment model is configured. Set JAC_ASSESSMENT_MODEL "
                "or provide model_identifier explicitly."
            )
        return model.strip()

    def _document_a(self) -> DocumentAInput:
        try:
            return DocumentAInputService(self.database).prepare()
        except DocumentAInputUnavailableError as error:
            raise AssessmentContextError(str(error)) from error

    def _assessment_prompt(self) -> _PromptInput:
        with self.database.session() as session:
            definitions = tuple(
                definition
                for definition in PromptDefinitionRepository(session).list(enabled_only=True)
                if definition.pipeline_group == ASSESSMENT_PIPELINE_GROUP
            )
            if len(definitions) != 1:
                raise AssessmentContextError(
                    "Assessment requires exactly one enabled prompt definition in "
                    "pipeline group 'assessment'."
                )
            definition = definitions[0]
            asset = ReferenceAssetRepository(session).get_active(definition.asset_key)
            if asset is None:
                raise AssessmentContextError(
                    f"Assessment prompt '{definition.asset_key}' has no active version."
                )
            if (
                asset.asset_type is not ReferenceAssetType.PROMPT
                or asset.processing_status is not ReferenceAssetProcessingStatus.READY
            ):
                raise AssessmentContextError(
                    f"Assessment prompt '{definition.asset_key}' is not an active READY prompt."
                )
            asset_key = asset.asset_key
            version = asset.version
            expected_hash = asset.file_hash
            relative_path = asset.file_path

        try:
            path = resolve_path_within(
                self.settings.prompts_folder,
                self.settings.reference_folder / relative_path,
            )
            content = path.read_bytes()
            text = content.decode("utf-8")
        except (ImmutableFilePathError, OSError, UnicodeError) as error:
            raise AssessmentContextError(
                f"Assessment prompt '{asset_key}' version {version} cannot be read safely."
            ) from error
        if not text.strip():
            raise AssessmentContextError(
                f"Assessment prompt '{asset_key}' version {version} is blank."
            )
        if sha256_file_hash(content) != expected_hash:
            raise AssessmentContextError(
                f"Assessment prompt '{asset_key}' version {version} no longer matches "
                "its recorded hash."
            )
        return _PromptInput(
            asset_key=asset_key,
            version=version,
            file_hash=expected_hash,
            text=text,
        )

    def _routing(self) -> _RoutingInput:
        with self.database.session() as session:
            document_b = ReferenceAssetRepository(session).get_active(DOCUMENT_B_KEY)
            if document_b is None:
                raise AssessmentContextError(
                    "No active Document B routing configuration is available for "
                    "assessment lane validation."
                )
            repository = DocumentBRoutingRepository(session)
            routing_set = repository.get_current(document_b.id)
            if routing_set is None or routing_set.status is not DocumentBRoutingSetStatus.VALIDATED:
                raise AssessmentContextError(
                    "The active Document B version has no current validated routing set."
                )
            lanes = tuple(route.lane_id for route in repository.list_routes(routing_set.id))
            if not lanes:
                raise AssessmentContextError(
                    "The active Document B routing set contains no permitted assessment lanes."
                )
            return _RoutingInput(
                routing_set_id=routing_set.id,
                routing_config_version=routing_set.routing_config_version,
                allowed_lane_ids=lanes,
            )


def _cache_identity(traceability: AssessmentTraceability) -> AssessmentCacheIdentity:
    components: dict[str, object] = {
        "identity_version": ASSESSMENT_CACHE_IDENTITY_VERSION,
        "operation": ASSESSMENT_PIPELINE_STEP,
        "pipeline_step": ASSESSMENT_PIPELINE_STEP,
        "model_identifier": traceability.model_identifier,
        "document_a_version": traceability.document_a_version,
        "document_a_hash": traceability.document_a_hash,
        "prompt_asset_key": traceability.prompt_asset_key,
        "prompt_version": traceability.prompt_version,
        "prompt_hash": traceability.prompt_hash,
        "schema_version": traceability.schema_version,
        "schema_hash": traceability.schema_hash,
    }
    return AssessmentCacheIdentity(
        identity_version=ASSESSMENT_CACHE_IDENTITY_VERSION,
        identity_hash=hashlib.sha256(_canonical_json(components).encode("utf-8")).hexdigest(),
        operation="ASSESSMENT",
        pipeline_step="ASSESSMENT",
        model_identifier=traceability.model_identifier,
        document_a_version=traceability.document_a_version,
        document_a_hash=traceability.document_a_hash,
        prompt_asset_key=traceability.prompt_asset_key,
        prompt_version=traceability.prompt_version,
        prompt_hash=traceability.prompt_hash,
        schema_version=traceability.schema_version,
        schema_hash=traceability.schema_hash,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
