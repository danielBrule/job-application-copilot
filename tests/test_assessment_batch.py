"""Integration tests for selected-job initial assessment queueing."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from job_application_copilot.domain import (
    AssessmentStatus,
    BackgroundOperation,
    BackgroundTaskStatus,
    Language,
    Location,
)
from job_application_copilot.repositories import (
    AssessmentRepository,
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    JobRepository,
    create_database,
)
from job_application_copilot.repositories.job_repository import JobNotFoundError
from job_application_copilot.repositories.models import (
    Assessment,
    BackgroundBatch,
    BackgroundTask,
    Job,
)
from job_application_copilot.services.assessment_batch import (
    AssessmentBatchService,
    AssessmentQueueSkipReason,
)
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    path = tmp_path / "assessment-batch.db"
    initialize_database(path)
    database = create_database(path)
    try:
        yield database
    finally:
        database.dispose()


def add_job(database: Database, company: str) -> int:
    with database.session() as session:
        job = Job(
            company=company,
            job_title="Platform Engineer",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Build reliable systems.",
            date_added=date(2026, 7, 30),
        )
        session.add(job)
        session.flush()
        return job.id


def add_assessment(database: Database, job_id: int) -> None:
    with database.session() as session:
        AssessmentRepository(session).add(
            Assessment(
                job_id=job_id,
                status=AssessmentStatus.FAILED,
                error_message="Timed out.",
            )
        )


def add_successful_assessment(database: Database, job_id: int, *, stale: bool) -> None:
    with database.session() as session:
        job = JobRepository(session).require(job_id)
        AssessmentRepository(session).add(
            Assessment(
                job_id=job_id,
                status=AssessmentStatus.ASSESSED,
                model_relevance="HIGH",
                role_snapshot="Role snapshot",
                real_mandate="Real mandate",
                primary_role_family="FICTIONAL_ARCHITECTURE_LEAD",
                seniority_fit=8,
                technical_bar="Technical bar",
                fit_score=8,
                priority_score=8,
                decision="GO",
                decision_reason="Good fit.",
                recommended_document_b_lane="FICTIONAL_ARCHITECTURE_LEAD",
                assessed_at=job.created_at,
                source_job_updated_at=(
                    datetime(2000, 1, 1, tzinfo=UTC) if stale else job.assessment_input_updated_at
                ),
            )
        )


def add_active_task(database: Database, job_id: int) -> None:
    with database.session() as session:
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        )
        BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=job_id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )


def test_queues_selected_eligible_jobs_in_one_batch_only(database: Database) -> None:
    first_id = add_job(database, "First")
    second_id = add_job(database, "Second")
    unselected_id = add_job(database, "Unselected")

    result = AssessmentBatchService(database).queue_selected((second_id, first_id))

    assert result.batch_id is not None
    assert result.queued_job_ids == (second_id, first_id)
    assert result.skipped == ()
    with database.session() as session:
        tasks = BackgroundTaskRepository(session).list(batch_id=result.batch_id)
        assert [task.job_id for task in tasks] == [second_id, first_id]
        assert all(task.status is BackgroundTaskStatus.PENDING for task in tasks)
        assert BackgroundTaskRepository(session).list(job_id=unselected_id) == []


def test_queues_all_unassessed_jobs_and_skips_active_work(database: Database) -> None:
    eligible_id = add_job(database, "Eligible")
    assessed_id = add_job(database, "Assessed")
    queued_id = add_job(database, "Queued")
    add_assessment(database, assessed_id)
    add_active_task(database, queued_id)

    result = AssessmentBatchService(database).queue_all_unassessed()

    assert result.batch_id is not None
    assert result.queued_job_ids == (eligible_id,)
    assert {(skip.job_id, skip.reason) for skip in result.skipped} == {
        (assessed_id, AssessmentQueueSkipReason.EXISTING_ASSESSMENT),
        (queued_id, AssessmentQueueSkipReason.ASSESSMENT_ALREADY_QUEUED),
    }


def test_selection_eligibility_separates_initial_and_reassessment_actions(
    database: Database,
) -> None:
    initial_id = add_job(database, "Initial")
    stale_id = add_job(database, "Stale")
    failed_id = add_job(database, "Failed")
    current_id = add_job(database, "Current")
    queued_id = add_job(database, "Queued")
    add_successful_assessment(database, stale_id, stale=True)
    add_assessment(database, failed_id)
    add_successful_assessment(database, current_id, stale=False)
    add_active_task(database, queued_id)

    result = AssessmentBatchService(database).selection_eligibility(
        (initial_id, stale_id, failed_id, current_id, queued_id)
    )

    assert result.initial_assessment_job_ids == (initial_id,)
    assert result.reassessment_job_ids == (stale_id, failed_id)


def test_skips_jobs_with_existing_assessments_or_active_tasks(database: Database) -> None:
    eligible_id = add_job(database, "Eligible")
    assessed_id = add_job(database, "Assessed")
    queued_id = add_job(database, "Queued")
    add_assessment(database, assessed_id)
    add_active_task(database, queued_id)

    result = AssessmentBatchService(database).queue_selected((eligible_id, assessed_id, queued_id))

    assert result.batch_id is not None
    assert result.queued_job_ids == (eligible_id,)
    assert [(item.job_id, item.reason) for item in result.skipped] == [
        (assessed_id, AssessmentQueueSkipReason.EXISTING_ASSESSMENT),
        (queued_id, AssessmentQueueSkipReason.ASSESSMENT_ALREADY_QUEUED),
    ]


def test_deduplicates_selection_and_does_not_create_an_empty_batch(database: Database) -> None:
    job_id = add_job(database, "Assessed")
    add_assessment(database, job_id)

    result = AssessmentBatchService(database).queue_selected((job_id, job_id))

    assert result.batch_id is None
    assert result.queued_job_ids == ()
    assert [(item.job_id, item.reason) for item in result.skipped] == [
        (job_id, AssessmentQueueSkipReason.EXISTING_ASSESSMENT),
    ]
    with database.session() as session:
        assert BackgroundTaskRepository(session).list() == []


def test_missing_job_rolls_back_without_creating_a_partial_batch(database: Database) -> None:
    eligible_id = add_job(database, "Eligible")

    with pytest.raises(JobNotFoundError):
        AssessmentBatchService(database).queue_selected((eligible_id, 999))

    with database.session() as session:
        assert BackgroundTaskRepository(session).list() == []


def test_queues_failed_and_stale_assessments_together(database: Database) -> None:
    stale_id = add_job(database, "Stale")
    failed_id = add_job(database, "Failed")
    current_id = add_job(database, "Current")
    unassessed_id = add_job(database, "Unassessed")
    queued_id = add_job(database, "Queued")
    add_successful_assessment(database, stale_id, stale=True)
    add_assessment(database, failed_id)
    add_successful_assessment(database, current_id, stale=False)
    add_assessment(database, queued_id)
    add_active_task(database, queued_id)

    result = AssessmentBatchService(database).queue_reassessment_selected(
        (stale_id, failed_id, current_id, unassessed_id, queued_id)
    )

    assert result.batch_id is not None
    assert result.queued_job_ids == (stale_id, failed_id)
    assert [(item.job_id, item.reason) for item in result.skipped] == [
        (current_id, AssessmentQueueSkipReason.ASSESSMENT_NOT_STALE),
        (unassessed_id, AssessmentQueueSkipReason.NO_ASSESSMENT),
        (queued_id, AssessmentQueueSkipReason.ASSESSMENT_ALREADY_QUEUED),
    ]
    with database.session() as session:
        tasks = BackgroundTaskRepository(session).list(batch_id=result.batch_id)
        assert [task.job_id for task in tasks] == [stale_id, failed_id]


def test_reassessment_deduplicates_and_does_not_create_an_empty_batch(database: Database) -> None:
    current_id = add_job(database, "Current")
    add_successful_assessment(database, current_id, stale=False)

    result = AssessmentBatchService(database).queue_reassessment_selected((current_id, current_id))

    assert result.batch_id is None
    assert result.queued_job_ids == ()
    assert [(item.job_id, item.reason) for item in result.skipped] == [
        (current_id, AssessmentQueueSkipReason.ASSESSMENT_NOT_STALE),
    ]


def test_missing_job_rolls_back_reassessment_without_creating_a_partial_batch(
    database: Database,
) -> None:
    stale_id = add_job(database, "Stale")
    add_successful_assessment(database, stale_id, stale=True)

    with pytest.raises(JobNotFoundError):
        AssessmentBatchService(database).queue_reassessment_selected((stale_id, 999))

    with database.session() as session:
        assert BackgroundTaskRepository(session).list() == []
