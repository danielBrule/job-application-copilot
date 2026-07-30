"""Bridge claimed assessment tasks to the assessment execution pipeline."""

from __future__ import annotations

from collections.abc import Callable

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import BackgroundOperation
from job_application_copilot.llm import OpenAIClient
from job_application_copilot.repositories import BackgroundTaskRepository, Database
from job_application_copilot.repositories.models import BackgroundTask
from job_application_copilot.services.assessment_context import AssessmentContextBuilder
from job_application_copilot.services.assessment_execution import AssessmentExecutionService
from job_application_copilot.services.assessment_persistence import AssessmentPersistenceService

ASSESSMENT_PIPELINE_STEP = "ASSESSMENT"


class AssessmentTaskFailedError(RuntimeError):
    """Signal that execution reached a recorded terminal assessment failure."""


class AssessmentWorkerHandler:
    """Execute one claimed assessment task and retain its assessment and usage records."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        *,
        client_factory: Callable[[AppSettings], OpenAIClient] = OpenAIClient.from_settings,
        context_builder: AssessmentContextBuilder | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client_factory = client_factory
        self.context_builder = context_builder
        self.persistence = AssessmentPersistenceService(database)

    def __call__(self, task: BackgroundTask) -> None:
        """Run one worker-claimed task, preserving a prior valid reassessment result."""

        if task.operation is not BackgroundOperation.ASSESSMENT:
            raise ValueError("Assessment handler received a non-assessment task.")

        task_attempt_id = self._start(task.id)
        self.persistence.mark_running(task.job_id)
        client: OpenAIClient | None = None
        try:
            client = self.client_factory(self.settings)
            result = AssessmentExecutionService(
                self.database,
                self.settings,
                client,
                context_builder=self.context_builder,
            ).assess(
                task.job_id,
                task_id=task.id,
                task_attempt_id=task_attempt_id,
            )
            self.persistence.persist(result)
            if not result.succeeded:
                raise AssessmentTaskFailedError(result.error_message)
        except AssessmentTaskFailedError:
            raise
        except Exception:
            self.persistence.mark_worker_failure(task.job_id)
            raise
        finally:
            if client is not None:
                client.close()

    def _start(self, task_id: int) -> int:
        with self.database.session() as session:
            tasks = BackgroundTaskRepository(session)
            task = tasks.require(task_id)
            tasks.set_pipeline_step(task, ASSESSMENT_PIPELINE_STEP)
            attempt = tasks.get_running_attempt(task.id)
            if attempt is None:
                raise RuntimeError("A claimed assessment task has no running execution attempt.")
            return attempt.id
