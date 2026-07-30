"""Integration tests for atomic job application-service operations."""

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from job_application_copilot.domain import (
    AssessmentDecision,
    AssessmentStatus,
    BackgroundOperation,
    CreateJob,
    DocumentBRoutingSetStatus,
    JobFilters,
    Language,
    LlmCallStatus,
    Location,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
    Relevance,
    UpdateJob,
    UserDecision,
)
from job_application_copilot.repositories import (
    Database,
    create_database,
)
from job_application_copilot.repositories.models import (
    Assessment,
    BackgroundBatch,
    BackgroundTask,
    DocumentBLaneRoute,
    DocumentBRoutingSet,
    Job,
    LlmCall,
    ReferenceAsset,
)
from job_application_copilot.services import (
    DuplicateJobUrlError,
    InvalidCvLaneSelectionError,
    JobNotFoundError,
    JobService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def database_and_service(tmp_path: Path) -> tuple[Database, JobService]:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database, JobService(database)
    finally:
        database.dispose()


def create_command(company: str = "Example Ltd") -> CreateJob:
    return CreateJob(
        company=company,
        job_title="Platform Engineer",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Build and operate reliable systems.",
        date_added=date(2026, 7, 24),
        job_url="https://example.com/job",
        general_notes="Initial note",
    )


def update_command() -> UpdateJob:
    return UpdateJob(
        company="Entreprise SA",
        job_title="Directeur technique",
        location=Location.FR,
        language=Language.FR,
        source="Company website",
        job_description="Direction technique.",
        date_added=date(2026, 7, 20),
        job_url=None,
        general_notes=None,
        relevance_override=Relevance.HIGH,
        user_decision=UserDecision.PURSUE,
        application_status="Applied",
        application_date=date(2026, 7, 21),
        next_action="Prepare interview",
        next_action_date=date(2026, 7, 28),
        salary_expectation="EUR 150,000",
        closure_reason=None,
    )


def test_create_and_get_return_readable_job_after_transaction(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service

    created = service.create(create_command())
    stored = service.get(created.id)

    assert created.id is not None
    assert created.company == "Example Ltd"
    assert stored is not None
    assert stored.id == created.id
    assert stored.job_url == "https://example.com/job"
    assert stored.relevance_override is None
    assert stored.user_decision is UserDecision.UNDECIDED


def test_update_replaces_fields_clears_nullable_values_and_preserves_identity(
    database_and_service: tuple[Database, JobService],
) -> None:
    database, service = database_and_service
    created = service.create(create_command())
    old_timestamp = datetime(2000, 1, 1)
    with database.session() as session:
        stored = session.get(Job, created.id)
        assert stored is not None
        stored.updated_at = old_timestamp
    created_at = created.created_at

    updated = service.update(created.id, update_command())

    assert updated.id == created.id
    assert updated.created_at == created_at
    assert updated.updated_at > old_timestamp
    assert updated.updated_at.microsecond == 0
    assert updated.company == "Entreprise SA"
    assert updated.location is Location.FR
    assert updated.language is Language.FR
    assert updated.job_url is None
    assert updated.general_notes is None
    assert updated.relevance_override is Relevance.HIGH
    assert updated.user_decision is UserDecision.PURSUE
    assert updated.application_status == "Applied"
    assert updated.next_action == "Prepare interview"


def test_update_can_change_and_clear_relevance_override(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    created = service.create(create_command())

    high = service.update(
        created.id,
        replace(update_command(), relevance_override=Relevance.HIGH),
    )
    cleared = service.update(
        created.id,
        replace(update_command(), relevance_override=None),
    )

    assert high.relevance_override is Relevance.HIGH
    assert cleared.relevance_override is None


@pytest.mark.parametrize(
    "user_decision",
    tuple(UserDecision),
)
def test_update_human_review_persists_user_values_without_changing_model_assessment(
    database_and_service: tuple[Database, JobService],
    user_decision: UserDecision,
) -> None:
    database, service = database_and_service
    created = service.create(create_command())
    with database.session() as session:
        assessment = Assessment(
            job_id=created.id,
            status=AssessmentStatus.ASSESSED,
            model_relevance=Relevance.HIGH,
            role_snapshot="Role snapshot",
            real_mandate="Real mandate",
            primary_role_family="ARCHITECTURE",
            seniority_fit=8,
            technical_bar="Technical bar",
            fit_score=8,
            priority_score=8,
            decision=AssessmentDecision.GO,
            decision_reason="Strong fit.",
            recommended_document_b_lane="ARCHITECTURE",
            assessed_at=created.assessment_input_updated_at,
            source_job_updated_at=created.assessment_input_updated_at,
        )
        session.add(assessment)

    updated = service.update_human_review(
        created.id,
        user_decision=user_decision,
        assessment_notes="  Follow up on team structure.  ",
    )

    assert updated.job.user_decision is user_decision
    assert updated.job.assessment_input_updated_at == created.assessment_input_updated_at
    assert updated.assessment is not None
    assert updated.assessment.assessment_notes == "Follow up on team structure."
    assert updated.assessment.decision is AssessmentDecision.GO
    assert updated.assessment.decision_reason == "Strong fit."
    assert updated.is_stale is False


def test_update_human_review_persists_only_a_lane_from_active_document_b_routing(
    database_and_service: tuple[Database, JobService],
) -> None:
    database, service = database_and_service
    created = service.create(create_command())
    _add_assessed_job(database, created)
    _add_active_cv_lanes(database, ("ARCHITECTURE", "AI_DEPLOYMENT"))

    updated = service.update_human_review(
        created.id,
        user_decision=UserDecision.PURSUE,
        assessment_notes=None,
        selected_cv_lane="AI_DEPLOYMENT",
    )

    assert service.available_cv_lanes() == ("AI_DEPLOYMENT", "ARCHITECTURE")
    assert updated.assessment is not None
    assert updated.assessment.selected_cv_lane == "AI_DEPLOYMENT"
    assert updated.assessment.recommended_document_b_lane == "ARCHITECTURE"

    with pytest.raises(InvalidCvLaneSelectionError, match="not configured"):
        service.update_human_review(
            created.id,
            user_decision=UserDecision.PURSUE,
            assessment_notes=None,
            selected_cv_lane="UNSUPPORTED",
        )

    detail = service.assessment_detail(created.id)
    assert detail.assessment is not None
    assert detail.assessment.selected_cv_lane == "AI_DEPLOYMENT"


def _add_assessed_job(database: Database, job: Job) -> None:
    with database.session() as session:
        session.add(
            Assessment(
                job_id=job.id,
                status=AssessmentStatus.ASSESSED,
                model_relevance=Relevance.HIGH,
                role_snapshot="Role snapshot",
                real_mandate="Real mandate",
                primary_role_family="ARCHITECTURE",
                seniority_fit=8,
                technical_bar="Technical bar",
                fit_score=8,
                priority_score=8,
                decision=AssessmentDecision.GO,
                decision_reason="Strong fit.",
                recommended_document_b_lane="ARCHITECTURE",
                assessed_at=job.assessment_input_updated_at,
                source_job_updated_at=job.assessment_input_updated_at,
            )
        )


def _add_active_cv_lanes(database: Database, lanes: tuple[str, ...]) -> None:
    with database.session() as session:
        document_b = ReferenceAsset(
            asset_key="document-b",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document B",
            version=1,
            file_path="document_b/document-b-v0001.docx",
            file_hash="sha256:" + ("b" * 64),
            is_active=True,
            processing_status=ReferenceAssetProcessingStatus.READY,
        )
        session.add(document_b)
        session.flush()
        routing_set = DocumentBRoutingSet(
            reference_asset_id=document_b.id,
            routing_config_version="routing-v1",
            routing_config_sha256="sha256:" + ("c" * 64),
            document_b_file_sha256="sha256:" + ("b" * 64),
            extracted_section_catalog_sha256="sha256:" + ("d" * 64),
            status=DocumentBRoutingSetStatus.VALIDATED,
            is_current=True,
        )
        session.add(routing_set)
        session.flush()
        session.add_all(
            [
                DocumentBLaneRoute(
                    routing_set_id=routing_set.id,
                    lane_id=lane,
                    ordered_route_json="{}",
                    secondary_lane_constraints_json="{}",
                )
                for lane in lanes
            ]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company", "Changed Ltd"),
        ("job_title", "Changed title"),
        ("location", Location.FR),
        ("language", Language.FR),
        ("job_description", "Materially changed description."),
    ],
)
def test_each_assessment_input_edit_advances_stale_source_timestamp(
    database_and_service: tuple[Database, JobService],
    field: str,
    value: object,
) -> None:
    _, service = database_and_service
    created = service.create(create_command())
    original_timestamp = created.assessment_input_updated_at

    administrative_update = replace(
        update_command(),
        company=created.company,
        job_title=created.job_title,
        location=created.location,
        language=created.language,
        job_description=created.job_description,
        source=created.source,
        date_added=created.date_added,
        job_url=created.job_url,
        general_notes="Changed note",
        relevance_override=Relevance.HIGH,
        user_decision=UserDecision.PURSUE,
    )
    unchanged = service.update(created.id, administrative_update)
    assert unchanged.assessment_input_updated_at == original_timestamp

    changed = service.update(created.id, replace(administrative_update, **{field: value}))
    assert changed.assessment_input_updated_at > original_timestamp


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_url", None),
        ("source", "Company website"),
        ("general_notes", "Changed note"),
    ],
)
def test_non_assessment_input_edits_do_not_advance_stale_source_timestamp(
    database_and_service: tuple[Database, JobService],
    field: str,
    value: object,
) -> None:
    _, service = database_and_service
    created = service.create(create_command())
    original_timestamp = created.assessment_input_updated_at
    administrative_update = replace(
        update_command(),
        company=created.company,
        job_title=created.job_title,
        location=created.location,
        language=created.language,
        job_description=created.job_description,
    )
    unchanged = service.update(created.id, replace(administrative_update, **{field: value}))

    assert unchanged.assessment_input_updated_at == original_timestamp


def test_assessment_staleness_marks_relevant_edit_without_replacing_assessment(
    database_and_service: tuple[Database, JobService],
) -> None:
    database, service = database_and_service
    created = service.create(create_command())
    with database.session() as session:
        session.add(
            Assessment(
                job_id=created.id,
                status=AssessmentStatus.ASSESSED,
                model_relevance=Relevance.HIGH,
                role_snapshot="Role snapshot",
                real_mandate="Real mandate",
                primary_role_family="FICTIONAL_ARCHITECTURE_LEAD",
                seniority_fit=8,
                technical_bar="Technical bar",
                fit_score=8,
                priority_score=8,
                decision=AssessmentDecision.GO,
                decision_reason="Strong fit.",
                recommended_document_b_lane="FICTIONAL_ARCHITECTURE_LEAD",
                assessed_at=created.created_at,
                source_job_updated_at=created.assessment_input_updated_at,
            )
        )

    updated = service.update(
        created.id,
        replace(update_command(), job_description="Materially changed description."),
    )

    assert service.assessment_staleness((updated,)) == {created.id: True}
    with database.session() as session:
        assessment = session.scalar(select(Assessment).where(Assessment.job_id == created.id))
        assert assessment is not None
        assert assessment.status is AssessmentStatus.ASSESSED


def test_list_delegates_filters(database_and_service: tuple[Database, JobService]) -> None:
    _, service = database_and_service
    service.create(create_command("Alpha"))
    service.create(
        replace(
            create_command("Beta"),
            location=Location.FR,
            language=Language.FR,
            job_url=None,
        )
    )

    jobs = service.list(JobFilters(location=Location.FR))

    assert [job.company for job in jobs] == ["Beta"]


def test_delete_and_missing_job_errors(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    first = service.create(create_command("First"))
    second = service.create(replace(create_command("Second"), job_url=None))

    service.delete(first.id)

    assert service.get(first.id) is None
    assert service.get(second.id) is not None
    with pytest.raises(JobNotFoundError, match="Job 999"):
        service.update(999, update_command())
    with pytest.raises(JobNotFoundError, match="Job 999"):
        service.delete(999)


def test_delete_many_removes_selected_jobs_and_linked_local_history(
    database_and_service: tuple[Database, JobService],
) -> None:
    database, service = database_and_service
    removed = service.create(create_command("Remove"))
    retained = service.create(replace(create_command("Retain"), job_url=None))
    with database.session() as session:
        session.add(Assessment(job_id=removed.id))
        batch = BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        session.add(batch)
        session.flush()
        task = BackgroundTask(
            batch_id=batch.id,
            job_id=removed.id,
            operation=BackgroundOperation.ASSESSMENT,
        )
        session.add(task)
        session.flush()
        session.add(
            LlmCall(
                job_id=removed.id,
                task_id=task.id,
                operation=BackgroundOperation.ASSESSMENT,
                pipeline_step="ASSESSMENT",
                call_sequence=1,
                provider="OPENAI",
                requested_model="gpt-test",
                status=LlmCallStatus.SUCCEEDED,
                retry_number=0,
                response_id="resp-test",
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                version_metadata={},
                started_at=datetime(2026, 7, 29, 10, 0, 0),
                completed_at=datetime(2026, 7, 29, 10, 0, 1),
                duration_seconds=1.0,
            )
        )

    assert service.delete_many((removed.id, removed.id)) == 1
    assert service.get(removed.id) is None
    assert service.get(retained.id) is not None
    with database.session() as session:
        assert (
            session.scalars(select(Assessment).where(Assessment.job_id == removed.id)).all() == []
        )
        assert (
            session.scalars(select(BackgroundTask).where(BackgroundTask.job_id == removed.id)).all()
            == []
        )
        assert session.scalars(select(LlmCall).where(LlmCall.job_id == removed.id)).all() == []


def test_create_rejects_exact_duplicate_non_null_url(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    existing = service.create(create_command("First"))

    with pytest.raises(DuplicateJobUrlError) as captured:
        service.create(create_command("Duplicate"))

    assert captured.value.existing_job_id == existing.id
    assert [job.company for job in service.list()] == ["First"]


def test_create_allows_null_and_distinct_urls(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service

    service.create(replace(create_command("No URL 1"), job_url=None))
    service.create(replace(create_command("No URL 2"), job_url=None))
    service.create(create_command("Exact URL"))
    service.create(
        replace(
            create_command("Trailing slash"),
            job_url="https://example.com/job/",
        )
    )

    assert {job.company for job in service.list()} == {
        "No URL 1",
        "No URL 2",
        "Exact URL",
        "Trailing slash",
    }


def test_update_allows_own_url_and_rejects_another_jobs_url(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    first = service.create(create_command("First"))
    second = service.create(
        replace(
            create_command("Second"),
            job_url="https://example.com/second",
        )
    )

    own_url_update = replace(update_command(), job_url=first.job_url)
    service.update(first.id, own_url_update)

    duplicate_update = replace(
        update_command(),
        company="Must roll back",
        job_url=second.job_url,
    )
    with pytest.raises(DuplicateJobUrlError) as captured:
        service.update(first.id, duplicate_update)

    assert captured.value.existing_job_id == second.id
    stored = service.get(first.id)
    assert stored is not None
    assert stored.company == own_url_update.company
    assert stored.job_url == first.job_url


def test_failed_create_rolls_back(database_and_service: tuple[Database, JobService]) -> None:
    _, service = database_and_service

    with pytest.raises(IntegrityError):
        service.create(replace(create_command(), company="   "))

    assert service.list() == []


def test_failed_update_rolls_back_all_changes(
    database_and_service: tuple[Database, JobService],
) -> None:
    _, service = database_and_service
    created = service.create(create_command())
    invalid_update = replace(
        update_command(),
        company="   ",
        job_title="This must also roll back",
    )

    with pytest.raises(IntegrityError):
        service.update(created.id, invalid_update)

    stored = service.get(created.id)
    assert stored is not None
    assert stored.company == "Example Ltd"
    assert stored.job_title == "Platform Engineer"
