"""Compose inspectable context for the French review-and-rewrite stage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from job_application_copilot.domain import (
    ENGLISH_CV_TEMPLATE_KEY,
    FRENCH_CV_TEMPLATE_KEY,
    FinalCvOutput,
    Language,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.errors import ApplicationOperationError, ApplicationValidationError
from job_application_copilot.repositories import (
    BackgroundTaskRepository,
    CvGenerationFinalRepository,
    Database,
    FrenchAdaptationDraftRepository,
    JobRepository,
    PromptContentRepository,
    PromptDefinitionRepository,
    ReferenceAssetRepository,
)
from job_application_copilot.services.cv_template_contract import CvTemplateContractService
from job_application_copilot.services.french_adaptation_context import (
    FRENCH_GENERATION_PIPELINE_GROUP,
)
from job_application_copilot.services.immutable_file_storage import sha256_file_hash


class FrenchReviewContextError(ApplicationOperationError):
    """Raised when French prompt two cannot receive a safe, reproducible context."""


class FrenchReviewTextInput(BaseModel):
    """One ordered provider-neutral French-review input."""

    model_config = ConfigDict(frozen=True)

    section: str
    text: str


class FrenchReviewTraceability(BaseModel):
    """Versions and hashes that determine one French-review context."""

    model_config = ConfigDict(frozen=True)

    task_id: int
    target_locale: str
    model_identifier: str
    document_a_version: int
    document_b_version: int
    english_final_prompt_version: int
    french_adaptation_prompt_version: int
    french_review_prompt_asset_key: str
    french_review_prompt_version: int
    french_review_prompt_hash: str
    english_template_version: int
    english_template_hash: str
    french_template_version: int
    french_template_hash: str
    response_schema_hash: str
    french_reference_versions: tuple[str, ...]


class FrenchReviewContext(BaseModel):
    """Complete ordered input for French prompt two."""

    model_config = ConfigDict(frozen=True)

    input: tuple[FrenchReviewTextInput, ...]
    traceability: FrenchReviewTraceability


@dataclass(frozen=True, slots=True)
class _PromptInput:
    asset_key: str
    version: int
    file_hash: str
    text: str


@dataclass(frozen=True, slots=True)
class _StageInputs:
    english: FinalCvOutput
    french_draft: FinalCvOutput
    target_locale: str
    document_a_version: int
    document_b_version: int
    english_final_prompt_version: int
    french_adaptation_prompt_version: int
    english_template_version: int
    french_template_version: int
    french_reference_versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _TemplateInput:
    english_hash: str
    french_hash: str
    contract: str


class FrenchReviewContextBuilder:
    """Build French stage-two input without invoking OpenAI or persisting output."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def build(
        self,
        task_id: int,
        *,
        model_identifier: str,
        response_schema: dict[str, Any],
    ) -> FrenchReviewContext:
        model = model_identifier.strip()
        if not model:
            raise FrenchReviewContextError("A French-review model identifier is required.")

        inputs = self._stage_inputs(task_id)
        prompt = self._prompt()
        template = self._template(inputs)
        schema_hash = sha256_file_hash(_canonical_json(response_schema).encode("utf-8"))

        return FrenchReviewContext(
            input=(
                FrenchReviewTextInput(
                    section="final_english_cv", text=inputs.english.model_dump_json()
                ),
                FrenchReviewTextInput(
                    section="french_adaptation_draft",
                    text=inputs.french_draft.model_dump_json(),
                ),
                FrenchReviewTextInput(section="target_locale", text=inputs.target_locale),
                FrenchReviewTextInput(section="stage_instructions", text=prompt.text),
                FrenchReviewTextInput(
                    section="evidence_authority",
                    text=(
                        "The final English CV is the sole factual authority. The French draft is "
                        "text to review, not an additional evidence source. Preserve every factual "
                        "claim, evidence-strength boundary, ownership qualifier and approved "
                        "positioning from the English source."
                    ),
                ),
                FrenchReviewTextInput(section="template_contract", text=template.contract),
            ),
            traceability=FrenchReviewTraceability(
                task_id=task_id,
                target_locale=inputs.target_locale,
                model_identifier=model,
                document_a_version=inputs.document_a_version,
                document_b_version=inputs.document_b_version,
                english_final_prompt_version=inputs.english_final_prompt_version,
                french_adaptation_prompt_version=inputs.french_adaptation_prompt_version,
                french_review_prompt_asset_key=prompt.asset_key,
                french_review_prompt_version=prompt.version,
                french_review_prompt_hash=prompt.file_hash,
                english_template_version=inputs.english_template_version,
                english_template_hash=template.english_hash,
                french_template_version=inputs.french_template_version,
                french_template_hash=template.french_hash,
                response_schema_hash=schema_hash,
                french_reference_versions=inputs.french_reference_versions,
            ),
        )

    def _stage_inputs(self, task_id: int) -> _StageInputs:
        with self.database.session() as session:
            task = BackgroundTaskRepository(session).require(task_id)
            if JobRepository(session).require(task.job_id).language is not Language.FR:
                raise FrenchReviewContextError(
                    "French review requires a job configured for French."
                )
            english = CvGenerationFinalRepository(session).require_for_task(task_id)
            draft = FrenchAdaptationDraftRepository(session).require_for_task(task_id)

        if (
            draft.document_a_version,
            draft.document_b_version,
            draft.english_final_prompt_version,
        ) != (
            english.document_a_version,
            english.document_b_version,
            english.prompt_version,
        ):
            raise FrenchReviewContextError(
                "The French adaptation draft does not match the retained final English CV."
            )
        try:
            english_output = FinalCvOutput.model_validate(english.payload)
            french_output = FinalCvOutput.model_validate(draft.payload)
        except ValueError as error:
            raise FrenchReviewContextError(
                "A retained CV input for French review failed validation."
            ) from error
        return _StageInputs(
            english=english_output,
            french_draft=french_output,
            target_locale=draft.target_locale,
            document_a_version=draft.document_a_version,
            document_b_version=draft.document_b_version,
            english_final_prompt_version=draft.english_final_prompt_version,
            french_adaptation_prompt_version=draft.french_prompt_version,
            english_template_version=draft.english_template_version,
            french_template_version=draft.french_template_version,
            french_reference_versions=tuple(draft.french_reference_versions),
        )

    def _prompt(self) -> _PromptInput:
        with self.database.session() as session:
            definitions = [
                definition
                for definition in PromptDefinitionRepository(session).list(enabled_only=True)
                if definition.pipeline_group == FRENCH_GENERATION_PIPELINE_GROUP
                and definition.position == 2
            ]
            if len(definitions) != 1:
                raise FrenchReviewContextError(
                    "French review stage requires exactly one enabled prompt at position two."
                )
            definition = definitions[0]
            asset = ReferenceAssetRepository(session).get_active(definition.asset_key)
            if (
                asset is None
                or asset.asset_type is not ReferenceAssetType.PROMPT
                or asset.processing_status is not ReferenceAssetProcessingStatus.READY
            ):
                raise FrenchReviewContextError(
                    f"French-review prompt '{definition.asset_key}' is not READY."
                )
            content = PromptContentRepository(session).get(asset.id)
            if content is None:
                raise FrenchReviewContextError(
                    f"French-review prompt '{definition.asset_key}' has no retained text."
                )
            prompt = _PromptInput(
                asset_key=asset.asset_key,
                version=asset.version,
                file_hash=asset.file_hash,
                text=content.content,
            )
        if (
            not prompt.text.strip()
            or sha256_file_hash(prompt.text.encode("utf-8")) != prompt.file_hash
        ):
            raise FrenchReviewContextError(
                f"French-review prompt '{prompt.asset_key}' failed integrity validation."
            )
        return prompt

    def _template(self, inputs: _StageInputs) -> _TemplateInput:
        try:
            contract = CvTemplateContractService(self.database).active()
            contract.validate(inputs.english)
            contract.validate(inputs.french_draft)
        except ApplicationValidationError as error:
            raise FrenchReviewContextError(
                "The retained French-review inputs do not match the active template contract."
            ) from error
        with self.database.session() as session:
            assets = ReferenceAssetRepository(session)
            english = assets.get_active(ENGLISH_CV_TEMPLATE_KEY)
            french = assets.get_active(FRENCH_CV_TEMPLATE_KEY)
            if english is None or french is None:
                raise FrenchReviewContextError(
                    "Active English and French CV templates are required for French review."
                )
            if french.processing_status is not ReferenceAssetProcessingStatus.READY:
                raise FrenchReviewContextError(
                    "An active READY French CV template is required for French review."
                )
            if (english.version, french.version) != (
                inputs.english_template_version,
                inputs.french_template_version,
            ):
                raise FrenchReviewContextError(
                    "The French adaptation draft does not match the active CV templates."
                )
            return _TemplateInput(
                english_hash=english.file_hash,
                french_hash=french.file_hash,
                contract=contract.prompt_input(),
            )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
