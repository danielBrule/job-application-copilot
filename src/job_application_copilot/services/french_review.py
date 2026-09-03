"""Execute and retain the French CV review-and-rewrite stage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    CvTemplateSlotKind,
    FinalCvOutput,
    SemanticFinalCvOutput,
)
from job_application_copilot.llm import (
    OpenAIPromptStageOperations,
    PromptStageInput,
    PromptStageRequest,
)
from job_application_copilot.repositories import Database, FrenchAdaptationFinalRepository
from job_application_copilot.repositories.models import BackgroundTask
from job_application_copilot.services.cv_template_contract import (
    CvTemplateContract,
    CvTemplateContractService,
)
from job_application_copilot.services.french_adaptation import FrenchAdaptationService
from job_application_copilot.services.french_review_context import (
    FrenchReviewContext,
    FrenchReviewContextBuilder,
)
from job_application_copilot.services.ordered_prompt_pipeline import (
    OrderedPromptPipelineResult,
    OrderedPromptPipelineService,
    OrderedPromptStage,
)

FRENCH_REVIEW_PIPELINE_POSITION = 5
FRENCH_REVIEW_PIPELINE_STEP = "CV_GENERATION_FRENCH_STAGE_2_REVIEW"


@dataclass(frozen=True, slots=True)
class FrenchReviewResult:
    """Validated saved output from French review and rewrite."""

    output: FinalCvOutput
    pipeline: OrderedPromptPipelineResult


class FrenchReviewService:
    """Review a retained French draft and persist the final French CV content."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        client: OpenAIPromptStageOperations,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client
        self.context_builder = FrenchReviewContextBuilder(database)
        self.template_contracts = CvTemplateContractService(database)

    def run(self, task: BackgroundTask, *, task_attempt_id: int) -> FrenchReviewResult:
        contract = self.template_contracts.active()
        response_schema = self._response_schema(contract)
        context = self.context_builder.build(
            task.id,
            model_identifier=self.settings.cv_generation_final_model,
            response_schema=response_schema,
        )
        english_output = FinalCvOutput.model_validate_json(context.input[0].text)
        stage = OrderedPromptStage(
            position=FRENCH_REVIEW_PIPELINE_POSITION,
            pipeline_step=FRENCH_REVIEW_PIPELINE_STEP,
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
            FrenchAdaptationFinalRepository(session).store(
                task_id=task.id,
                output=output,
                target_locale=trace.target_locale,
                document_a_version=trace.document_a_version,
                document_b_version=trace.document_b_version,
                english_final_prompt_version=trace.english_final_prompt_version,
                french_adaptation_prompt_version=trace.french_adaptation_prompt_version,
                french_review_prompt_version=trace.french_review_prompt_version,
                english_template_version=trace.english_template_version,
                french_template_version=trace.french_template_version,
                french_reference_versions=trace.french_reference_versions,
            )
        return FrenchReviewResult(output=output, pipeline=pipeline)

    def _request(
        self,
        context: FrenchReviewContext,
        prior: str | None,
        response_schema: dict[str, object],
    ) -> PromptStageRequest:
        if prior is not None:
            raise ValueError("French review cannot receive output from another pipeline run.")
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
    def _validated_pipeline_output(text: str, contract: CvTemplateContract) -> FinalCvOutput:
        output = FinalCvOutput.model_validate_json(text)
        contract.validate(output)
        return output
