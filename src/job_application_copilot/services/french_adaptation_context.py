"""Compose inspectable context for the first French CV adaptation stage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    ENGLISH_CV_TEMPLATE_KEY,
    FRENCH_CV_TEMPLATE_KEY,
    FinalCvOutput,
    FrenchReferencePassage,
    Language,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.errors import ApplicationOperationError, ApplicationValidationError
from job_application_copilot.repositories import (
    BackgroundTaskRepository,
    CvGenerationFinalRepository,
    Database,
    JobRepository,
    PromptContentRepository,
    PromptDefinitionRepository,
    ReferenceAssetRepository,
)
from job_application_copilot.services.cv_template_contract import CvTemplateContractService
from job_application_copilot.services.cv_template_manifest import CvTemplateManifestService
from job_application_copilot.services.immutable_file_storage import (
    resolve_path_within,
    sha256_file_hash,
)

FRENCH_GENERATION_PIPELINE_GROUP = "generation/french"


class FrenchAdaptationContextError(ApplicationOperationError):
    """Raised when French stage one cannot receive a safe, reproducible context."""


class FrenchAdaptationTextInput(BaseModel):
    """One ordered provider-neutral French-adaptation input."""

    model_config = ConfigDict(frozen=True)

    section: str
    text: str


class FrenchAdaptationTraceability(BaseModel):
    """Versions and hashes that determine one French-adaptation context."""

    model_config = ConfigDict(frozen=True)

    task_id: int
    model_identifier: str
    document_a_version: int
    document_b_version: int
    english_final_prompt_version: int
    french_prompt_asset_key: str
    french_prompt_version: int
    french_prompt_hash: str
    english_template_version: int
    english_template_hash: str
    french_template_version: int
    french_template_hash: str
    response_schema_hash: str
    french_reference_versions: tuple[str, ...]


class FrenchAdaptationContext(BaseModel):
    """Complete ordered input for French prompt one."""

    model_config = ConfigDict(frozen=True)

    input: tuple[FrenchAdaptationTextInput, ...]
    traceability: FrenchAdaptationTraceability


@dataclass(frozen=True, slots=True)
class _PromptInput:
    asset_key: str
    version: int
    file_hash: str
    text: str


@dataclass(frozen=True, slots=True)
class _EnglishFinalInput:
    output: FinalCvOutput
    document_a_version: int
    document_b_version: int
    prompt_version: int


@dataclass(frozen=True, slots=True)
class _TemplateInput:
    english_version: int
    english_hash: str
    french_version: int
    french_hash: str
    contract: str


class FrenchAdaptationContextBuilder:
    """Build French stage-one input without invoking OpenAI or persisting output."""

    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings

    def build(
        self,
        task_id: int,
        *,
        model_identifier: str,
        response_schema: dict[str, Any],
        references: tuple[FrenchReferencePassage, ...] = (),
    ) -> FrenchAdaptationContext:
        """Return context whose first item is the complete final English CV."""

        model = model_identifier.strip()
        if not model:
            raise FrenchAdaptationContextError("A French-adaptation model identifier is required.")

        final = self._english_final(task_id)
        prompt = self._prompt()
        template = self._templates(final.output)
        self._validate_references(references)
        schema_hash = sha256_file_hash(_canonical_json(response_schema).encode("utf-8"))

        items = [
            FrenchAdaptationTextInput(
                section="final_english_cv",
                text=final.output.model_dump_json(),
            ),
            FrenchAdaptationTextInput(section="stage_instructions", text=prompt.text),
            FrenchAdaptationTextInput(
                section="evidence_preservation",
                text=(
                    "Adapt the supplied final English CV into French without adding, removing, "
                    "strengthening or weakening evidence. Preserve all metrics, dates, employers, "
                    "technologies, outcomes, scope and ownership boundaries. French role wording "
                    "may be idiomatic, but its factual meaning and seniority must remain unchanged. "
                    "Copy literal personal facts such as phone numbers exactly. French references "
                    "are style and terminology guidance only and are never factual evidence."
                ),
            ),
            FrenchAdaptationTextInput(section="template_contract", text=template.contract),
        ]
        if references:
            items.append(
                FrenchAdaptationTextInput(
                    section="french_style_references",
                    text=_canonical_json(
                        [reference.model_dump(mode="json") for reference in references]
                    ),
                )
            )

        return FrenchAdaptationContext(
            input=tuple(items),
            traceability=FrenchAdaptationTraceability(
                task_id=task_id,
                model_identifier=model,
                document_a_version=final.document_a_version,
                document_b_version=final.document_b_version,
                english_final_prompt_version=final.prompt_version,
                french_prompt_asset_key=prompt.asset_key,
                french_prompt_version=prompt.version,
                french_prompt_hash=prompt.file_hash,
                english_template_version=template.english_version,
                english_template_hash=template.english_hash,
                french_template_version=template.french_version,
                french_template_hash=template.french_hash,
                response_schema_hash=schema_hash,
                french_reference_versions=tuple(
                    f"{reference.asset_key}:v{reference.version}" for reference in references
                ),
            ),
        )

    def _english_final(self, task_id: int) -> _EnglishFinalInput:
        with self.database.session() as session:
            task = BackgroundTaskRepository(session).require(task_id)
            job = JobRepository(session).require(task.job_id)
            if job.language is not Language.FR:
                raise FrenchAdaptationContextError(
                    "French adaptation requires a job configured for French."
                )
            stored = CvGenerationFinalRepository(session).get_for_task(task_id)
            if stored is None:
                raise FrenchAdaptationContextError(
                    "French adaptation requires the completed final English CV output."
                )
            try:
                output = FinalCvOutput.model_validate(stored.payload)
            except ValueError as error:
                raise FrenchAdaptationContextError(
                    "The retained final English CV output failed validation."
                ) from error
            return _EnglishFinalInput(
                output=output,
                document_a_version=stored.document_a_version,
                document_b_version=stored.document_b_version,
                prompt_version=stored.prompt_version,
            )

    def _prompt(self) -> _PromptInput:
        with self.database.session() as session:
            definitions = [
                definition
                for definition in PromptDefinitionRepository(session).list(enabled_only=True)
                if definition.pipeline_group == FRENCH_GENERATION_PIPELINE_GROUP
                and definition.position == 1
            ]
            if len(definitions) != 1:
                raise FrenchAdaptationContextError(
                    "French adaptation stage one requires exactly one enabled French prompt."
                )
            definition = definitions[0]
            asset = ReferenceAssetRepository(session).get_active(definition.asset_key)
            if (
                asset is None
                or asset.asset_type is not ReferenceAssetType.PROMPT
                or asset.processing_status is not ReferenceAssetProcessingStatus.READY
            ):
                raise FrenchAdaptationContextError(
                    f"French-adaptation prompt '{definition.asset_key}' is not READY."
                )
            content = PromptContentRepository(session).get(asset.id)
            if content is None:
                raise FrenchAdaptationContextError(
                    f"French-adaptation prompt '{definition.asset_key}' has no retained text."
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
            raise FrenchAdaptationContextError(
                f"French-adaptation prompt '{prompt.asset_key}' failed integrity validation."
            )
        return prompt

    def _templates(self, output: FinalCvOutput) -> _TemplateInput:
        try:
            contract = CvTemplateContractService(self.database).active()
            contract.validate(output)
        except ApplicationValidationError as error:
            raise FrenchAdaptationContextError(
                "The final English CV does not match the active English template contract."
            ) from error

        with self.database.session() as session:
            assets = ReferenceAssetRepository(session)
            english = assets.get_active(ENGLISH_CV_TEMPLATE_KEY)
            french = assets.get_active(FRENCH_CV_TEMPLATE_KEY)
            if english is None:
                raise FrenchAdaptationContextError("An active English CV template is required.")
            if (
                french is None
                or french.processing_status is not ReferenceAssetProcessingStatus.READY
            ):
                raise FrenchAdaptationContextError(
                    "An active READY French CV template is required for French adaptation."
                )
            if french.file_path is None:
                raise FrenchAdaptationContextError("The active French CV template has no file.")
            english_version, english_hash = english.version, english.file_hash
            french_version, french_hash = french.version, french.file_hash
            french_path = french.file_path

        try:
            path = resolve_path_within(
                self.settings.reference_folder,
                self.settings.reference_folder / french_path,
            )
            content = path.read_bytes()
        except (OSError, ValueError) as error:
            raise FrenchAdaptationContextError(
                "The active French CV template could not be read safely."
            ) from error
        if sha256_file_hash(content) != french_hash:
            raise FrenchAdaptationContextError(
                "The active French CV template failed integrity validation."
            )
        try:
            CvTemplateManifestService(self.database, self.settings).validate_french_template(
                content
            )
        except ApplicationValidationError as error:
            raise FrenchAdaptationContextError(str(error)) from error
        return _TemplateInput(
            english_version=english_version,
            english_hash=english_hash,
            french_version=french_version,
            french_hash=french_hash,
            contract=contract.prompt_input(),
        )

    def _validate_references(self, references: tuple[FrenchReferencePassage, ...]) -> None:
        with self.database.session() as session:
            assets = ReferenceAssetRepository(session)
            for reference in references:
                if (
                    not reference.style_reference_only
                    or reference.source_metadata.get("style_reference_only", "").lower() != "true"
                ):
                    raise FrenchAdaptationContextError(
                        "French CV references must be explicitly labelled as style-only."
                    )
                asset = assets.get_active(reference.asset_key)
                if (
                    asset is None
                    or asset.id != reference.reference_asset_id
                    or asset.version != reference.version
                    or asset.asset_type is not ReferenceAssetType.REFERENCE_EXAMPLE
                    or asset.language_code != "fr"
                    or asset.processing_status is not ReferenceAssetProcessingStatus.READY
                ):
                    raise FrenchAdaptationContextError(
                        "A French style reference is no longer an active verified source."
                    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
