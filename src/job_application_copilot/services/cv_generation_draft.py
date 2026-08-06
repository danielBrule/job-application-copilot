"""Execute and retain the structured second stage of English CV generation."""

import hashlib
import json
from dataclasses import asdict, dataclass

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import CvGenerationBriefOutput, CvGenerationDraftOutput
from job_application_copilot.llm import (
    OpenAIPromptStageOperations,
    PromptStageInput,
    PromptStageRequest,
)
from job_application_copilot.repositories import (
    CvGenerationBriefRepository,
    CvGenerationDraftRepository,
    Database,
)
from job_application_copilot.repositories.models import BackgroundTask
from job_application_copilot.services.cv_generation_context import (
    CvGenerationBriefInput,
    CvGenerationContext,
    CvGenerationContextBuilder,
)
from job_application_copilot.services.ordered_prompt_pipeline import (
    OrderedPromptPipelineResult,
    OrderedPromptPipelineService,
    OrderedPromptStage,
)

CV_DRAFT_PIPELINE_STEP = "CV_GENERATION_STAGE_2_DRAFT"


@dataclass(frozen=True, slots=True)
class CvGenerationDraftResult:
    """Validated saved output from generation stage two."""

    output: CvGenerationDraftOutput
    pipeline: OrderedPromptPipelineResult


class CvGenerationDraftService:
    """Generate one reusable first CV draft from a retained authorised brief."""

    def __init__(
        self, database: Database, settings: AppSettings, client: OpenAIPromptStageOperations
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client
        self.context_builder = CvGenerationContextBuilder(database, settings)

    def run(self, task: BackgroundTask, *, task_attempt_id: int) -> CvGenerationDraftResult:
        brief = self._brief_for_task(task.id)
        context = self.context_builder.build(
            task.job_id,
            stage=2,
            model_identifier=self.settings.cv_generation_model,
            response_schema=CvGenerationDraftOutput.model_json_schema(),
            brief=brief,
        )
        stage = OrderedPromptStage(
            position=2,
            pipeline_step=CV_DRAFT_PIPELINE_STEP,
            request_factory=lambda prior: self._request(context, prior),
            output_validator=lambda text: self._validated_output(text).model_dump_json(),
        )
        pipeline = OrderedPromptPipelineService(
            self.database,
            self.client,
            max_retries=self.settings.cv_generation_max_retries,
        ).run(task, task_attempt_id=task_attempt_id, stages=(stage,))
        output = self._validated_output(pipeline.outputs[0])
        with self.database.session() as session:
            CvGenerationDraftRepository(session).store(
                task_id=task.id,
                output=output,
                document_a_version=context.traceability.document_a_version,
                document_b_version=context.traceability.document_b_version,
                routing_set_id=context.traceability.routing_set_id,
                prompt_version=context.traceability.prompt_version,
            )
        return CvGenerationDraftResult(output=output, pipeline=pipeline)

    def _brief_for_task(self, task_id: int) -> CvGenerationBriefInput:
        with self.database.session() as session:
            stored = CvGenerationBriefRepository(session).require_for_task(task_id)
        return CvGenerationBriefInput(
            document_a_version=stored.document_a_version,
            document_b_version=stored.document_b_version,
            routing_set_id=stored.routing_set_id,
            output=CvGenerationBriefOutput.model_validate(stored.payload),
        )

    def _request(self, context: CvGenerationContext, prior: str | None) -> PromptStageRequest:
        if prior is not None:
            raise ValueError(
                "CV-generation stage two cannot receive pipeline output from another run."
            )
        inputs = tuple(
            PromptStageInput(
                section=item.section, text=item.text, cache_boundary=item.cache_boundary
            )
            for item in context.input
        )
        execution_identity = hashlib.sha256(
            json.dumps([asdict(item) for item in inputs], sort_keys=True).encode("utf-8")
        ).hexdigest()
        return PromptStageRequest(
            model_identifier=context.traceability.model_identifier,
            input=inputs,
            cache_identity_hash=context.cache_identity.identity_hash,
            cache_identity_version=context.cache_identity.identity_version,
            execution_identity_hash=execution_identity,
            response_schema=CvGenerationDraftOutput.model_json_schema(),
            reasoning_effort=self.settings.cv_generation_reasoning_effort,
        )

    @staticmethod
    def _validated_output(text: str) -> CvGenerationDraftOutput:
        return CvGenerationDraftOutput.model_validate_json(text)
