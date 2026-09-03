"""Execute and retain the first French CV adaptation stage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Protocol

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    CvTemplateSlotKind,
    FinalCvOutput,
    FrenchReferenceRetrievalRequest,
    SemanticFinalCvOutput,
)
from job_application_copilot.llm import (
    OpenAIPromptStageOperations,
    OpenAIVectorStoreOperations,
    PromptStageInput,
    PromptStageRequest,
)
from job_application_copilot.repositories import (
    CvGenerationFinalRepository,
    Database,
    FrenchAdaptationDraftRepository,
)
from job_application_copilot.repositories.models import BackgroundTask
from job_application_copilot.services.cv_template_contract import (
    CvTemplateContract,
    CvTemplateContractService,
)
from job_application_copilot.services.french_adaptation_context import (
    FrenchAdaptationContext,
    FrenchAdaptationContextBuilder,
)
from job_application_copilot.services.french_reference_indexing import (
    FrenchReferenceRetrievalService,
)
from job_application_copilot.services.ordered_prompt_pipeline import (
    OrderedPromptPipelineResult,
    OrderedPromptPipelineService,
    OrderedPromptStage,
)

FRENCH_ADAPTATION_PIPELINE_POSITION = 4
FRENCH_ADAPTATION_PIPELINE_STEP = "CV_GENERATION_FRENCH_STAGE_1_ADAPTATION"


class FrenchAdaptationOperations(
    OpenAIPromptStageOperations, OpenAIVectorStoreOperations, Protocol
):
    """Provider capabilities required by French adaptation stage one."""


@dataclass(frozen=True, slots=True)
class FrenchAdaptationResult:
    """Validated saved output from French adaptation stage one."""

    output: FinalCvOutput
    pipeline: OrderedPromptPipelineResult


class FrenchAdaptationService:
    """Adapt a retained final English CV and persist the structured French draft."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        client: FrenchAdaptationOperations,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client
        self.context_builder = FrenchAdaptationContextBuilder(database, settings)
        self.template_contracts = CvTemplateContractService(database)

    def run(self, task: BackgroundTask, *, task_attempt_id: int) -> FrenchAdaptationResult:
        contract = self.template_contracts.active()
        response_schema = self._response_schema(contract)
        english_output = self._english_final(task.id)
        references = FrenchReferenceRetrievalService(self.database, self.client).retrieve(
            FrenchReferenceRetrievalRequest(query=self._reference_query(english_output))
        )
        context = self.context_builder.build(
            task.id,
            model_identifier=self.settings.cv_generation_model,
            response_schema=response_schema,
            references=references,
        )
        stage = OrderedPromptStage(
            position=FRENCH_ADAPTATION_PIPELINE_POSITION,
            pipeline_step=FRENCH_ADAPTATION_PIPELINE_STEP,
            request_factory=lambda prior: self._request(context, prior, response_schema),
            output_validator=lambda text: self._validated_contract_output(
                text, contract, english_output
            ).model_dump_json(),
        )
        pipeline = OrderedPromptPipelineService(
            self.database,
            self.client,
            max_retries=self.settings.cv_generation_max_retries,
        ).run(task, task_attempt_id=task_attempt_id, stages=(stage,))
        output = self._validated_pipeline_output(pipeline.outputs[0], contract)
        trace = context.traceability
        with self.database.session() as session:
            FrenchAdaptationDraftRepository(session).store(
                task_id=task.id,
                output=output,
                target_locale=trace.target_locale,
                document_a_version=trace.document_a_version,
                document_b_version=trace.document_b_version,
                english_final_prompt_version=trace.english_final_prompt_version,
                french_prompt_version=trace.french_prompt_version,
                english_template_version=trace.english_template_version,
                french_template_version=trace.french_template_version,
                french_reference_versions=trace.french_reference_versions,
            )
        return FrenchAdaptationResult(output=output, pipeline=pipeline)

    def _english_final(self, task_id: int) -> FinalCvOutput:
        with self.database.session() as session:
            stored = CvGenerationFinalRepository(session).require_for_task(task_id)
            return FinalCvOutput.model_validate(stored.payload)

    @staticmethod
    def _reference_query(output: FinalCvOutput) -> str:
        parts = [output.opening_title.content, output.opening_profile.content]
        parts.extend(f"{entry.name}: {entry.content}" for entry in output.skills.entries)
        for experience in output.experience:
            if experience.title is not None:
                parts.append(experience.title.content)
            if experience.introduction is not None:
                parts.append(experience.introduction)
            parts.extend(experience.bullets)
        return "\n".join(parts)

    def _request(
        self,
        context: FrenchAdaptationContext,
        prior: str | None,
        response_schema: dict[str, object],
    ) -> PromptStageRequest:
        if prior is not None:
            raise ValueError("French adaptation cannot receive output from another pipeline run.")
        inputs = tuple(
            PromptStageInput(section=item.section, text=item.text) for item in context.input
        )
        identity = hashlib.sha256(
            json.dumps(
                {
                    "inputs": [asdict(item) for item in inputs],
                    "model_identifier": context.traceability.model_identifier,
                    "response_schema": response_schema,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return PromptStageRequest(
            model_identifier=context.traceability.model_identifier,
            input=inputs,
            cache_identity_hash=identity,
            cache_identity_version=1,
            execution_identity_hash=identity,
            response_schema=response_schema,
            reasoning_effort=self.settings.cv_generation_reasoning_effort,
        )

    @staticmethod
    def _response_schema(contract: CvTemplateContract) -> dict[str, object]:
        schema = SemanticFinalCvOutput.model_json_schema()
        properties = schema["properties"]
        assert isinstance(properties, dict)
        experience = properties["experience_blocks"]
        assert isinstance(experience, dict)
        expected_count = sum(
            slot.kind is CvTemplateSlotKind.EXPERIENCE for slot in contract.manifest.slots
        )
        experience["minItems"] = expected_count
        experience["maxItems"] = expected_count
        return schema

    @staticmethod
    def _validated_contract_output(
        text: str,
        contract: CvTemplateContract,
        english_output: FinalCvOutput,
    ) -> FinalCvOutput:
        semantic = SemanticFinalCvOutput.model_validate_json(text)
        output = contract.bind_semantic_output(semantic)
        contract.validate(output)
        FrenchAdaptationService._validate_matching_structure(english_output, output)
        return output

    @staticmethod
    def _validate_matching_structure(
        english_output: FinalCvOutput, french_output: FinalCvOutput
    ) -> None:
        if len(english_output.skills.entries) != len(french_output.skills.entries):
            raise ValueError("French adaptation must preserve the number of skill entries.")
        for english, french in zip(
            english_output.experience, french_output.experience, strict=True
        ):
            if (english.title is None) != (french.title is None):
                raise ValueError("French adaptation must preserve experience-title structure.")
            if (english.introduction is None) != (french.introduction is None):
                raise ValueError(
                    "French adaptation must preserve experience-introduction structure."
                )
            if len(english.bullets) != len(french.bullets):
                raise ValueError(
                    "French adaptation must preserve the number of experience bullets."
                )

    @staticmethod
    def _validated_pipeline_output(text: str, contract: CvTemplateContract) -> FinalCvOutput:
        output = FinalCvOutput.model_validate_json(text)
        contract.validate(output)
        return output
