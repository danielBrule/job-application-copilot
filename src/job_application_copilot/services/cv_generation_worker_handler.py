"""Bridge claimed CV-generation tasks to the language-specific generation workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    ENGLISH_CV_TEMPLATE_KEY,
    FRENCH_CV_TEMPLATE_KEY,
    BackgroundOperation,
    CvSource,
    Language,
)
from job_application_copilot.llm import OpenAIClient
from job_application_copilot.repositories import (
    AssessmentRepository,
    CvGenerationBriefRepository,
    CvGenerationDraftRepository,
    CvGenerationFinalRepository,
    Database,
    FrenchAdaptationFinalRepository,
    JobRepository,
)
from job_application_copilot.repositories.background_task_repository import (
    BackgroundTaskRepository,
)
from job_application_copilot.repositories.models import BackgroundTask
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.assessment_context import AssessmentContextBuilder
from job_application_copilot.services.assessment_execution import AssessmentExecutionService
from job_application_copilot.services.assessment_persistence import AssessmentPersistenceService
from job_application_copilot.services.cv_document_renderer import CvDocumentRendererService
from job_application_copilot.services.cv_generation_brief import CvGenerationBriefService
from job_application_copilot.services.cv_generation_draft import CvGenerationDraftService
from job_application_copilot.services.cv_generation_final import CvGenerationFinalService
from job_application_copilot.services.cv_service import CvService
from job_application_copilot.services.french_adaptation import FrenchAdaptationService
from job_application_copilot.services.french_review import FrenchReviewService

CV_RENDER_PIPELINE_STEP = "CV_GENERATION_RENDER_DOCX"
ASSESSMENT_CONTRACT_REFRESH_PIPELINE_STEP = "ASSESSMENT_CONTRACT_REFRESH"


class CvGenerationAssessmentRefreshError(RuntimeError):
    """Raised when required assessment refresh prevents CV generation."""


@dataclass(frozen=True, slots=True)
class CvGenerationMetadata:
    """Traceability values attached to the generated local CV record."""

    company: str
    selected_cv_lane: str
    document_a_version: int
    document_b_version: int
    template_version: int
    generation_prompt_versions: dict[str, int]
    french_prompt_versions: dict[str, int] | None = None


class CvGenerationWorkerHandler:
    """Run one claimed CV-generation task through its implemented language stages."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        *,
        client_factory: Callable[[AppSettings], OpenAIClient] = OpenAIClient.from_settings,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client_factory = client_factory
        self.cv_service = CvService(database, settings)
        self.assessment_persistence = AssessmentPersistenceService(database)

    def __call__(self, task: BackgroundTask) -> None:
        """Run the English stages, then extend FR-language CVs with French stages."""

        if task.operation is not BackgroundOperation.CV_GENERATION:
            raise ValueError("CV-generation handler received a non-CV-generation task.")

        task_attempt_id = self._task_attempt_id(task.id)
        client: OpenAIClient | None = None
        try:
            client = self.client_factory(self.settings)
            self._refresh_assessment_if_contract_stale(task, task_attempt_id, client)
            CvGenerationBriefService(self.database, self.settings, client).run(
                task, task_attempt_id=task_attempt_id
            )
            CvGenerationDraftService(self.database, self.settings, client).run(
                task, task_attempt_id=task_attempt_id
            )
            final = CvGenerationFinalService(self.database, self.settings, client).run(
                task, task_attempt_id=task_attempt_id
            )
            language = self._language(task.id)
            output = final.output
            if language is Language.FR:
                FrenchAdaptationService(self.database, self.settings, client).run(
                    task, task_attempt_id=task_attempt_id
                )
                french_final = FrenchReviewService(self.database, self.settings, client).run(
                    task, task_attempt_id=task_attempt_id
                )
                output = french_final.output
            self._set_pipeline_step(task.id, CV_RENDER_PIPELINE_STEP)
            metadata = self._metadata(task.id)
            file_path = CvDocumentRendererService(self.database, self.settings).render(
                output,
                company=metadata.company,
                language=language,
            )
            self.cv_service.record_ready(
                job_id=task.job_id,
                source=CvSource.GENERATED,
                language=language,
                file_path=file_path,
                selected_cv_lane=metadata.selected_cv_lane,
                document_a_version=metadata.document_a_version,
                document_b_version=metadata.document_b_version,
                template_version=metadata.template_version,
                generation_prompt_versions=metadata.generation_prompt_versions,
                french_prompt_versions=metadata.french_prompt_versions,
            )
        finally:
            if client is not None:
                client.close()

    def _language(self, task_id: int) -> Language:
        with self.database.session() as session:
            task = BackgroundTaskRepository(session).require(task_id)
            return JobRepository(session).require(task.job_id).language

    def _refresh_assessment_if_contract_stale(
        self,
        task: BackgroundTask,
        task_attempt_id: int,
        client: OpenAIClient,
    ) -> None:
        """Refresh an obsolete assessment before CV-generation stage one."""

        contract = AssessmentContextBuilder(self.database, self.settings).current_contract()
        with self.database.session() as session:
            assessment = AssessmentRepository(session).require_for_job(task.job_id)
            if AssessmentRepository.is_current_contract(
                assessment,
                document_a_version=contract.document_a_version,
                prompt_version=contract.prompt_version,
            ):
                return

        self._set_pipeline_step(task.id, ASSESSMENT_CONTRACT_REFRESH_PIPELINE_STEP)
        result = AssessmentExecutionService(self.database, self.settings, client).assess(
            task.job_id,
            task_id=task.id,
            task_attempt_id=task_attempt_id,
        )
        self.assessment_persistence.persist(result)
        if not result.succeeded:
            raise CvGenerationAssessmentRefreshError(
                "CV generation requires a refreshed assessment: "
                f"{result.error_message or 'assessment did not complete.'}"
            )

    def _task_attempt_id(self, task_id: int) -> int:
        with self.database.session() as session:
            attempt = BackgroundTaskRepository(session).get_running_attempt(task_id)
            if attempt is None:
                raise RuntimeError("A claimed CV-generation task has no running execution attempt.")
            return attempt.id

    def _set_pipeline_step(self, task_id: int, pipeline_step: str) -> None:
        with self.database.session() as session:
            tasks = BackgroundTaskRepository(session)
            tasks.set_pipeline_step(tasks.require(task_id), pipeline_step)

    def _metadata(self, task_id: int) -> CvGenerationMetadata:
        with self.database.session() as session:
            task = BackgroundTaskRepository(session).require(task_id)
            job = JobRepository(session).require(task.job_id)
            brief = CvGenerationBriefRepository(session).require_for_task(task_id)
            draft = CvGenerationDraftRepository(session).require_for_task(task_id)
            final = CvGenerationFinalRepository(session).require_for_task(task_id)
            if (draft.document_a_version, draft.document_b_version, draft.routing_set_id) != (
                brief.document_a_version,
                brief.document_b_version,
                brief.routing_set_id,
            ) or (final.document_a_version, final.document_b_version, final.routing_set_id) != (
                brief.document_a_version,
                brief.document_b_version,
                brief.routing_set_id,
            ):
                raise ValueError("CV-generation stages do not share the same retained inputs.")
            french_final = (
                FrenchAdaptationFinalRepository(session).require_for_task(task_id)
                if job.language is Language.FR
                else None
            )
            template_key = (
                FRENCH_CV_TEMPLATE_KEY if job.language is Language.FR else ENGLISH_CV_TEMPLATE_KEY
            )
            template = ReferenceAssetRepository(session).get_active(template_key)
            if template is None:
                raise RuntimeError("The rendered CV has no active template metadata.")
            if french_final is not None:
                if (
                    french_final.document_a_version,
                    french_final.document_b_version,
                    french_final.english_final_prompt_version,
                ) != (
                    brief.document_a_version,
                    brief.document_b_version,
                    final.prompt_version,
                ):
                    raise ValueError(
                        "French and English CV-generation stages do not share the same retained "
                        "inputs."
                    )
                if french_final.french_template_version != template.version:
                    raise ValueError(
                        "The reviewed French CV does not match the active French template."
                    )
            return CvGenerationMetadata(
                company=job.company,
                selected_cv_lane=brief.target_cv_lane,
                document_a_version=brief.document_a_version,
                document_b_version=brief.document_b_version,
                template_version=template.version,
                generation_prompt_versions={
                    "stage_1": brief.prompt_version,
                    "stage_2": draft.prompt_version,
                    "stage_3": final.prompt_version,
                },
                french_prompt_versions=(
                    None
                    if french_final is None
                    else {
                        "adaptation": french_final.french_adaptation_prompt_version,
                        "review": french_final.french_review_prompt_version,
                    }
                ),
            )
