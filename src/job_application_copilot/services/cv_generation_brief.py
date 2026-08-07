"""Execute and retain the structured first stage of English CV generation."""

import hashlib
import json
from dataclasses import asdict, dataclass

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import CvGenerationBriefOutput, DocumentBRouteRole
from job_application_copilot.llm import (
    OpenAIPromptStageOperations,
    PromptStageInput,
    PromptStageRequest,
)
from job_application_copilot.repositories import CvGenerationBriefRepository, Database
from job_application_copilot.repositories.models import BackgroundTask
from job_application_copilot.services.cv_generation_context import (
    CvGenerationContext,
    CvGenerationContextBuilder,
)
from job_application_copilot.services.ordered_prompt_pipeline import (
    OrderedPromptPipelineResult,
    OrderedPromptPipelineService,
    OrderedPromptStage,
)

CV_BRIEF_PIPELINE_STEP = "CV_GENERATION_STAGE_1_BRIEF"


@dataclass(frozen=True, slots=True)
class CvGenerationBriefResult:
    """Validated saved output from generation stage one."""

    output: CvGenerationBriefOutput
    pipeline: OrderedPromptPipelineResult


class CvGenerationBriefService:
    """Build, execute, validate and retain one reusable CV-generation brief."""

    def __init__(
        self, database: Database, settings: AppSettings, client: OpenAIPromptStageOperations
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client
        self.context_builder = CvGenerationContextBuilder(database, settings)

    def run(self, task: BackgroundTask, *, task_attempt_id: int) -> CvGenerationBriefResult:
        context = self.context_builder.build(
            task.job_id,
            stage=1,
            model_identifier=self.settings.cv_generation_model,
            response_schema=self._model_response_schema(),
        )
        stage = OrderedPromptStage(
            position=1,
            pipeline_step=CV_BRIEF_PIPELINE_STEP,
            request_factory=lambda prior: self._request(context, prior),
            output_validator=lambda text: self._validated_output(text, context).model_dump_json(),
        )
        pipeline = OrderedPromptPipelineService(
            self.database,
            self.client,
            max_retries=self.settings.cv_generation_max_retries,
        ).run(task, task_attempt_id=task_attempt_id, stages=(stage,))
        output = self._validated_output(pipeline.outputs[0], context)
        with self.database.session() as session:
            CvGenerationBriefRepository(session).store(
                task_id=task.id,
                output=output,
                document_a_version=context.traceability.document_a_version,
                document_b_version=context.traceability.document_b_version,
                routing_set_id=context.traceability.routing_set_id,
                prompt_version=context.traceability.prompt_version,
            )
        return CvGenerationBriefResult(output=output, pipeline=pipeline)

    def _request(self, context: CvGenerationContext, prior: str | None) -> PromptStageRequest:
        if prior is not None:
            raise ValueError(
                "CV-generation brief is the first stage and cannot receive prior output."
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
            response_schema=self._model_response_schema(),
            reasoning_effort=self.settings.cv_generation_reasoning_effort,
        )

    @staticmethod
    def _model_response_schema() -> dict[str, object]:
        """Return the stage-one schema without application-controlled values."""

        schema = CvGenerationBriefOutput.model_json_schema()
        properties = schema["properties"]
        assert isinstance(properties, dict)
        application_controlled_fields = {
            "target_cv_lane",
            "selected_passage_ids",
            "guardrail_ids",
        }
        for field in application_controlled_fields:
            properties.pop(field)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [
                field for field in required if field not in application_controlled_fields
            ]
        return schema

    @staticmethod
    def _validated_output(text: str, context: CvGenerationContext) -> CvGenerationBriefOutput:
        raw_output = json.loads(text)
        if not isinstance(raw_output, dict):
            raise ValueError("CV-generation brief must be a JSON object.")
        output = CvGenerationBriefOutput.model_validate(
            {
                **raw_output,
                "target_cv_lane": context.cache_identity.primary_lane,
                "selected_passage_ids": [],
                "guardrail_ids": [],
            }
        )
        mandatory = next(item for item in context.input if item.section == "mandatory_document_b")
        entries = json.loads(mandatory.text)
        section_ids = {entry["section_id"] for entry in entries}
        guardrail_ids = {
            entry["logical_id"]
            for entry in entries
            if entry.get("role") == DocumentBRouteRole.GUARDRAIL
        }
        output = output.model_copy(update={"guardrail_ids": frozenset(guardrail_ids)})
        if not output.selected_section_ids.issubset(section_ids):
            raise ValueError("CV-generation brief selected an unauthorised Document B section.")
        if output.selected_passage_ids:
            raise ValueError("Stage-one brief cannot select passages that were not supplied.")
        return output
