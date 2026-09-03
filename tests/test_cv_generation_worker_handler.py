"""Worker integration tests for English CV-generation task handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import job_application_copilot.services.cv_generation_worker_handler as handler_module
from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    BackgroundOperation,
    BackgroundTaskStatus,
    CvSource,
    CvStatus,
    Language,
    Location,
    Relevance,
)
from job_application_copilot.repositories import (
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    CvRepository,
    Database,
    create_database,
)
from job_application_copilot.repositories.models import (
    Assessment,
    BackgroundBatch,
    BackgroundTask,
    Job,
)
from job_application_copilot.services import CvService
from job_application_copilot.services.background_worker import BackgroundWorker
from job_application_copilot.services.cv_generation_worker_handler import (
    CvGenerationMetadata,
    CvGenerationWorkerHandler,
)
from job_application_copilot.services.database_bootstrap import initialize_database


class FakeClient:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


@dataclass
class StageFakes:
    rendered_path: Path
    fail_task_id: int | None = None
    bypass_contract_refresh: bool = True

    def install(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []
        fail_task_id = self.fail_task_id
        rendered_path = self.rendered_path

        class Brief:
            def __init__(self, *args: object) -> None:
                del args

            def run(self, task: BackgroundTask, *, task_attempt_id: int) -> None:
                del task_attempt_id
                calls.append(f"brief:{task.id}")

        class Draft:
            def __init__(self, *args: object) -> None:
                del args

            def run(self, task: BackgroundTask, *, task_attempt_id: int) -> None:
                del task_attempt_id
                calls.append(f"draft:{task.id}")
                if task.id == fail_task_id:
                    raise RuntimeError("simulated stage-two failure")

        class Final:
            def __init__(self, *args: object) -> None:
                del args

            def run(self, task: BackgroundTask, *, task_attempt_id: int) -> SimpleNamespace:
                del task_attempt_id
                calls.append(f"final:{task.id}")
                return SimpleNamespace(output=object())

        class FrenchAdaptation:
            def __init__(self, *args: object) -> None:
                del args

            def run(self, task: BackgroundTask, *, task_attempt_id: int) -> None:
                del task_attempt_id
                calls.append(f"french-adaptation:{task.id}")

        class Renderer:
            def __init__(self, *args: object) -> None:
                del args

            def render(self, output: object, *, company: str) -> Path:
                del output
                calls.append(f"render:{company}")
                rendered_path.parent.mkdir(parents=True, exist_ok=True)
                rendered_path.write_bytes(b"rendered DOCX")
                return rendered_path

        monkeypatch.setattr(handler_module, "CvGenerationBriefService", Brief)
        monkeypatch.setattr(handler_module, "CvGenerationDraftService", Draft)
        monkeypatch.setattr(handler_module, "CvGenerationFinalService", Final)
        monkeypatch.setattr(handler_module, "FrenchAdaptationService", FrenchAdaptation)
        monkeypatch.setattr(handler_module, "CvDocumentRendererService", Renderer)
        if self.bypass_contract_refresh:
            monkeypatch.setattr(
                CvGenerationWorkerHandler,
                "_refresh_assessment_if_contract_stale",
                lambda self, task, task_attempt_id, client: None,
            )
        return calls


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database_path = tmp_path / "cv-worker.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database
    finally:
        database.dispose()


def add_tasks(
    database: Database, companies: list[str], *, language: Language = Language.EN
) -> list[BackgroundTask]:
    with database.session() as session:
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.CV_GENERATION)
        )
        tasks: list[BackgroundTask] = []
        for company in companies:
            job = Job(
                company=company,
                job_title="Platform Engineer",
                location=Location.UK,
                language=language,
                source="LinkedIn",
                job_description="Build reliable systems.",
                date_added=date(2026, 8, 7),
            )
            session.add(job)
            session.flush()
            tasks.append(
                BackgroundTaskRepository(session).add(
                    BackgroundTask(
                        batch_id=batch.id,
                        job_id=job.id,
                        operation=BackgroundOperation.CV_GENERATION,
                    )
                )
            )
        return tasks


def metadata(company: str) -> CvGenerationMetadata:
    return CvGenerationMetadata(
        company=company,
        selected_cv_lane="ARCHITECTURE",
        document_a_version=2,
        document_b_version=3,
        template_version=4,
        generation_prompt_versions={"stage_1": 5, "stage_2": 6, "stage_3": 7},
    )


def add_assessment(
    database: Database,
    job_id: int,
    *,
    document_a_version: int,
    prompt_version: int,
) -> None:
    with database.session() as session:
        job = session.get(Job, job_id)
        assert job is not None
        session.add(
            Assessment(
                job_id=job_id,
                status=AssessmentStatus.ASSESSED,
                model_relevance=Relevance.HIGH,
                role_snapshot="Role snapshot",
                real_mandate="Real mandate",
                primary_role_family="ARCHITECTURE",
                fit_score=8,
                priority_score=8,
                technical_bar="Technical bar",
                seniority_fit=8,
                decision=AssessmentDecision.GO,
                decision_reason="Strong fit.",
                recommended_document_b_lane="ARCHITECTURE",
                assessed_at=job.assessment_input_updated_at,
                source_job_updated_at=job.assessment_input_updated_at,
                document_a_version=document_a_version,
                prompt_version=prompt_version,
            )
        )


def test_english_task_runs_three_stages_renders_and_becomes_ready_for_review(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (task,) = add_tasks(database, ["Example Ltd"])
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    client = FakeClient()
    calls = StageFakes(settings.cv_folder / "rendered.docx").install(monkeypatch)
    monkeypatch.setattr(
        CvGenerationWorkerHandler,
        "_metadata",
        lambda self, task_id: metadata("Example Ltd"),
    )
    handler = CvGenerationWorkerHandler(
        database,
        settings,
        client_factory=lambda _: client,
    )

    assert BackgroundWorker(
        database, {BackgroundOperation.CV_GENERATION: handler}
    ).process_next_task()

    with database.session() as session:
        stored_task = BackgroundTaskRepository(session).require(task.id)
        cv = CvRepository(session).require_for_job(task.job_id)
        assert stored_task.status is BackgroundTaskStatus.COMPLETED
        assert stored_task.pipeline_step == "CV_GENERATION_RENDER_DOCX"
        assert cv.status is CvStatus.READY_FOR_REVIEW
        assert cv.source is CvSource.GENERATED
        assert cv.language is Language.EN
        assert cv.file_path == str(settings.cv_folder / "rendered.docx")
        assert cv.selected_cv_lane == "ARCHITECTURE"
        assert (cv.document_a_version, cv.document_b_version, cv.template_version) == (2, 3, 4)
        assert cv.generation_prompt_versions == {"stage_1": 5, "stage_2": 6, "stage_3": 7}
    assert calls == [
        f"brief:{task.id}",
        f"draft:{task.id}",
        f"final:{task.id}",
        "render:Example Ltd",
    ]
    assert client.close_count == 1


def test_failed_task_does_not_stop_a_sibling_cv_task(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed, completed = add_tasks(database, ["Failure Ltd", "Success Ltd"])
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.cv_folder.mkdir(parents=True)
    prior_file = settings.cv_folder / "prior.docx"
    prior_file.write_bytes(b"prior rendered DOCX")
    CvService(database, settings).record_ready(
        job_id=failed.job_id,
        source=CvSource.GENERATED,
        language=Language.EN,
        file_path=prior_file,
    )
    first_client = FakeClient()
    second_client = FakeClient()
    clients = iter((first_client, second_client))
    StageFakes(settings.cv_folder / "rendered.docx", fail_task_id=failed.id).install(monkeypatch)
    monkeypatch.setattr(
        CvGenerationWorkerHandler,
        "_metadata",
        lambda self, task_id: metadata("Success Ltd"),
    )
    handler = CvGenerationWorkerHandler(
        database,
        settings,
        client_factory=lambda _: next(clients),
    )
    worker = BackgroundWorker(database, {BackgroundOperation.CV_GENERATION: handler})

    assert worker.process_next_task()
    assert worker.process_next_task()

    with database.session() as session:
        assert (
            BackgroundTaskRepository(session).require(failed.id).status
            is BackgroundTaskStatus.FAILED
        )
        assert (
            BackgroundTaskRepository(session).require(completed.id).status
            is BackgroundTaskStatus.COMPLETED
        )
        prior_cv = CvRepository(session).require_for_job(failed.job_id)
        assert prior_cv.status is CvStatus.READY_FOR_REVIEW
        assert prior_cv.file_path == str(prior_file)
        assert (
            CvRepository(session).require_for_job(completed.job_id).status
            is CvStatus.READY_FOR_REVIEW
        )
    assert first_client.close_count == 1
    assert second_client.close_count == 1


def test_french_job_runs_adaptation_after_english_pipeline_without_rendering(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (task,) = add_tasks(database, ["French job"], language=Language.FR)
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    calls = StageFakes(settings.cv_folder / "rendered.docx").install(monkeypatch)
    monkeypatch.setattr(
        CvGenerationWorkerHandler,
        "_metadata",
        lambda self, task_id: metadata("French job"),
    )
    handler = CvGenerationWorkerHandler(
        database,
        settings,
        client_factory=lambda _: FakeClient(),
    )

    assert BackgroundWorker(
        database, {BackgroundOperation.CV_GENERATION: handler}
    ).process_next_task()

    with database.session() as session:
        assert (
            BackgroundTaskRepository(session).require(task.id).status
            is BackgroundTaskStatus.COMPLETED
        )
        assert CvRepository(session).get_for_job(task.job_id) is None
    assert calls == [
        f"brief:{task.id}",
        f"draft:{task.id}",
        f"final:{task.id}",
        f"french-adaptation:{task.id}",
    ]


def test_rejects_non_cv_generation_task(database: Database, tmp_path: Path) -> None:
    task = BackgroundTask(batch_id=1, job_id=1, operation=BackgroundOperation.ASSESSMENT)
    handler = CvGenerationWorkerHandler(
        database,
        AppSettings(_env_file=None, data_dir=tmp_path / "data"),
        client_factory=lambda _: FakeClient(),
    )

    with pytest.raises(ValueError, match="non-CV-generation"):
        handler(task)


def test_current_assessment_does_not_trigger_refresh(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (task,) = add_tasks(database, ["Current Ltd"])
    add_assessment(database, task.job_id, document_a_version=2, prompt_version=3)

    class ContextBuilder:
        def __init__(self, *args: object) -> None:
            del args

        def current_contract(self) -> SimpleNamespace:
            return SimpleNamespace(document_a_version=2, prompt_version=3)

    class Execution:
        def __init__(self, *args: object) -> None:
            raise AssertionError("A current assessment must not be reassessed.")

    monkeypatch.setattr(handler_module, "AssessmentContextBuilder", ContextBuilder)
    monkeypatch.setattr(handler_module, "AssessmentExecutionService", Execution)
    handler = CvGenerationWorkerHandler(
        database,
        AppSettings(_env_file=None, data_dir=tmp_path / "data"),
        client_factory=lambda _: FakeClient(),
    )

    handler._refresh_assessment_if_contract_stale(task, task_attempt_id=1, client=FakeClient())


@pytest.mark.parametrize(
    ("stored_document_a_version", "stored_prompt_version"),
    [(1, 3), (2, 2)],
)
def test_stale_assessment_contract_is_refreshed_before_cv_stages(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stored_document_a_version: int,
    stored_prompt_version: int,
) -> None:
    (task,) = add_tasks(database, ["Stale Ltd"])
    add_assessment(
        database,
        task.job_id,
        document_a_version=stored_document_a_version,
        prompt_version=stored_prompt_version,
    )
    calls: list[str] = []

    class ContextBuilder:
        def __init__(self, *args: object) -> None:
            del args

        def current_contract(self) -> SimpleNamespace:
            return SimpleNamespace(document_a_version=2, prompt_version=3)

    class Execution:
        def __init__(self, *args: object) -> None:
            del args

        def assess(self, job_id: int, **kwargs: object) -> SimpleNamespace:
            assert job_id == task.job_id
            assert kwargs == {"task_id": task.id, "task_attempt_id": 1}
            calls.append("assess")
            return SimpleNamespace(succeeded=True)

    monkeypatch.setattr(handler_module, "AssessmentContextBuilder", ContextBuilder)
    monkeypatch.setattr(handler_module, "AssessmentExecutionService", Execution)
    handler = CvGenerationWorkerHandler(
        database,
        AppSettings(_env_file=None, data_dir=tmp_path / "data"),
        client_factory=lambda _: FakeClient(),
    )
    monkeypatch.setattr(handler, "_set_pipeline_step", lambda *_: calls.append("step"))
    monkeypatch.setattr(
        handler.assessment_persistence, "persist", lambda _: calls.append("persist")
    )

    handler._refresh_assessment_if_contract_stale(task, task_attempt_id=1, client=FakeClient())

    assert calls == ["step", "assess", "persist"]


def test_failed_assessment_refresh_stops_cv_generation_before_stage_one(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (task,) = add_tasks(database, ["Failure Ltd"])
    add_assessment(database, task.job_id, document_a_version=1, prompt_version=1)
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    stage_calls = StageFakes(
        settings.cv_folder / "rendered.docx",
        bypass_contract_refresh=False,
    ).install(monkeypatch)

    class ContextBuilder:
        def __init__(self, *args: object) -> None:
            del args

        def current_contract(self) -> SimpleNamespace:
            return SimpleNamespace(document_a_version=2, prompt_version=2)

    class Execution:
        def __init__(self, *args: object) -> None:
            del args

        def assess(self, *args: object, **kwargs: object) -> SimpleNamespace:
            del args, kwargs
            return SimpleNamespace(succeeded=False, error_message="Assessment timed out")

    monkeypatch.setattr(handler_module, "AssessmentContextBuilder", ContextBuilder)
    monkeypatch.setattr(handler_module, "AssessmentExecutionService", Execution)
    handler = CvGenerationWorkerHandler(database, settings, client_factory=lambda _: FakeClient())
    persisted: list[object] = []
    monkeypatch.setattr(handler.assessment_persistence, "persist", persisted.append)

    assert BackgroundWorker(
        database, {BackgroundOperation.CV_GENERATION: handler}
    ).process_next_task()

    with database.session() as session:
        stored_task = BackgroundTaskRepository(session).require(task.id)
        assessment = session.get(Assessment, task.job_id)
        assert stored_task.status is BackgroundTaskStatus.FAILED
        assert assessment is not None
        assert assessment.document_a_version == 1
        assert assessment.prompt_version == 1
    assert len(persisted) == 1
    assert stage_calls == []
