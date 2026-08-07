"""Tests for durable, eligibility-gated CV-generation batch creation."""

from datetime import date

import pytest

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    BackgroundOperation,
    BackgroundTaskStatus,
    CvSelectionStatus,
    CvSource,
    CvStatus,
    Language,
    Location,
    Relevance,
    UserDecision,
)
from job_application_copilot.repositories import (
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    create_database,
)
from job_application_copilot.repositories.job_repository import JobNotFoundError
from job_application_copilot.repositories.models import (
    Assessment,
    BackgroundBatch,
    BackgroundTask,
    Cv,
    Job,
)
from job_application_copilot.services.cv_generation_batch import (
    CvGenerationBatchService,
    CvGenerationQueueSkipReason,
)
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def database(tmp_path) -> Database:
    database_path = tmp_path / "cv-generation-batch.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database
    finally:
        database.dispose()


@pytest.fixture(autouse=True)
def current_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        CvGenerationBatchService,
        "_current_lanes",
        staticmethod(lambda session: frozenset({"ARCHITECTURE"})),
    )


def add_job(
    database: Database,
    company: str,
    *,
    user_decision: UserDecision = UserDecision.PURSUE,
    selected: bool = True,
) -> Job:
    with database.session() as session:
        job = Job(
            company=company,
            job_title="Platform Architect",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Lead platform engineering.",
            date_added=date(2026, 8, 7),
            user_decision=user_decision,
            cv_selection_status=(
                CvSelectionStatus.SELECTED if selected else CvSelectionStatus.NOT_SELECTED
            ),
        )
        session.add(job)
        session.flush()
        return job


def add_assessment(
    database: Database,
    job: Job,
    *,
    status: AssessmentStatus = AssessmentStatus.ASSESSED,
    lane: str | None = "ARCHITECTURE",
    stale: bool = False,
) -> None:
    with database.session() as session:
        assessment = Assessment(
            job_id=job.id,
            status=status,
            model_relevance=Relevance.HIGH,
            role_snapshot="Lead platform engineering.",
            real_mandate="Improve delivery.",
            primary_role_family="ARCHITECTURE",
            seniority_fit=8,
            technical_bar="Platform architecture.",
            fit_score=8,
            priority_score=8,
            decision=AssessmentDecision.GO,
            decision_reason="Strong fit.",
            recommended_document_b_lane="ARCHITECTURE",
            selected_cv_lane=lane,
            assessed_at=job.assessment_input_updated_at,
            source_job_updated_at=(
                job.assessment_input_updated_at.replace(year=2025)
                if stale
                else job.assessment_input_updated_at
            ),
        )
        session.add(assessment)


def test_queue_selected_creates_one_batch_and_task_per_current_eligible_job(
    database: Database,
) -> None:
    first = add_job(database, "First Ltd")
    second = add_job(database, "Second Ltd")
    missing_lane = add_job(database, "Missing Lane Ltd")
    add_assessment(database, first)
    add_assessment(database, second)
    add_assessment(database, missing_lane, lane=None)

    result = CvGenerationBatchService(database).queue_selected(
        (second.id, first.id, second.id, missing_lane.id)
    )

    assert result.batch_id is not None
    assert result.queued_job_ids == (second.id, first.id)
    assert [(skip.job_id, skip.reason) for skip in result.skipped] == [
        (missing_lane.id, CvGenerationQueueSkipReason.MISSING_CV_LANE)
    ]
    with database.session() as session:
        tasks = BackgroundTaskRepository(session).list(batch_id=result.batch_id)
        assert [task.job_id for task in tasks] == [second.id, first.id]
        assert all(task.operation is BackgroundOperation.CV_GENERATION for task in tasks)


def test_queue_all_eligible_pursued_returns_actionable_skips(database: Database) -> None:
    eligible = add_job(database, "Eligible Ltd")
    stale = add_job(database, "Stale Ltd")
    missing_assessment = add_job(database, "Missing Ltd")
    not_selected = add_job(database, "Not Selected Ltd", selected=False)
    not_pursued = add_job(database, "Not Pursued Ltd", user_decision=UserDecision.UNDECIDED)
    add_assessment(database, eligible)
    add_assessment(database, stale, stale=True)
    add_assessment(database, not_selected)
    add_assessment(database, not_pursued)

    result = CvGenerationBatchService(database).queue_all_eligible_pursued()

    assert result.batch_id is not None
    assert result.queued_job_ids == (eligible.id,)
    assert {(skip.job_id, skip.reason) for skip in result.skipped} == {
        (stale.id, CvGenerationQueueSkipReason.ASSESSMENT_STALE),
        (missing_assessment.id, CvGenerationQueueSkipReason.MISSING_ASSESSMENT),
        (not_selected.id, CvGenerationQueueSkipReason.NOT_SELECTED),
    }


def test_selected_queue_is_atomic_when_a_job_is_missing(database: Database) -> None:
    eligible = add_job(database, "Eligible Ltd")
    add_assessment(database, eligible)

    with pytest.raises(JobNotFoundError):
        CvGenerationBatchService(database).queue_selected((eligible.id, 999))

    with database.session() as session:
        assert BackgroundTaskRepository(session).list() == []


def test_queue_selected_reports_noncurrent_lane_and_existing_pending_work(
    database: Database,
) -> None:
    noncurrent_lane = add_job(database, "Old lane Ltd")
    already_queued = add_job(database, "Queued Ltd")
    add_assessment(database, noncurrent_lane, lane="RETIRED_LANE")
    add_assessment(database, already_queued)
    with database.session() as session:
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.CV_GENERATION)
        )
        BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=already_queued.id,
                operation=BackgroundOperation.CV_GENERATION,
            )
        )

    result = CvGenerationBatchService(database).queue_selected(
        (noncurrent_lane.id, already_queued.id)
    )

    assert result.batch_id is None
    assert {(skip.job_id, skip.reason) for skip in result.skipped} == {
        (noncurrent_lane.id, CvGenerationQueueSkipReason.CV_LANE_NOT_CURRENT),
        (already_queued.id, CvGenerationQueueSkipReason.CV_GENERATION_ALREADY_QUEUED),
    }


def test_regeneration_queues_generated_and_failed_jobs_but_not_new_or_uploaded_jobs(
    database: Database,
) -> None:
    generated = add_job(database, "Generated Ltd")
    failed = add_job(database, "Failed Ltd")
    new = add_job(database, "New Ltd")
    uploaded = add_job(database, "Uploaded Ltd")
    for job in (generated, failed, new, uploaded):
        add_assessment(database, job)
    with database.session() as session:
        session.add(
            Cv(
                job_id=generated.id,
                source=CvSource.GENERATED,
                status=CvStatus.READY_FOR_REVIEW,
                language=Language.EN,
                file_name="generated.docx",
                file_path="C:/private/cvs/generated.docx",
            )
        )
        session.add(
            Cv(
                job_id=uploaded.id,
                source=CvSource.UPLOADED,
                status=CvStatus.READY_FOR_REVIEW,
                language=Language.EN,
                file_name="uploaded.docx",
                file_path="C:/private/cvs/uploaded.docx",
            )
        )
        failed_batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.CV_GENERATION)
        )
        BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=failed_batch.id,
                job_id=failed.id,
                operation=BackgroundOperation.CV_GENERATION,
                status=BackgroundTaskStatus.FAILED,
                error_message="Generation failed.",
            )
        )

    result = CvGenerationBatchService(database).queue_regeneration_selected(
        (generated.id, failed.id, new.id, uploaded.id)
    )

    assert result.batch_id is not None
    assert result.queued_job_ids == (generated.id, failed.id)
    assert {(skip.job_id, skip.reason) for skip in result.skipped} == {
        (new.id, CvGenerationQueueSkipReason.NO_GENERATION_TO_RESTART),
        (uploaded.id, CvGenerationQueueSkipReason.NO_GENERATION_TO_RESTART),
    }
