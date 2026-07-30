"""Tests for deterministic, evidence-grounded assessment context composition."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    ASSESSMENT_SCHEMA_VERSION,
    DocumentBRoutingSetStatus,
    Language,
    Location,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.models import (
    DocumentBLaneRoute,
    DocumentBRoutingSet,
    Job,
    ReferenceAsset,
)
from job_application_copilot.services import (
    AssessmentContextBuilder,
    AssessmentContextError,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.immutable_file_storage import sha256_file_hash

PROMPT_TEXT = "Use complete Document A only.\nReturn every required schema field.\n"
DOCUMENT_A_HASH = "sha256:" + ("a" * 64)
DOCUMENT_B_HASH = "sha256:" + ("b" * 64)
ROUTING_HASH = "sha256:" + ("c" * 64)
CATALOG_HASH = "sha256:" + ("d" * 64)
LANES = ("FICTIONAL_AI_LEAD", "FICTIONAL_ARCHITECTURE_LEAD")


@pytest.fixture
def context_setup(tmp_path: Path) -> tuple[Database, AppSettings, int]:
    settings = AppSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "database" / "copilot.db",
        reference_folder=tmp_path / "reference",
        assessment_model="gpt-test",
        _env_file=None,
    )
    settings.database_path.parent.mkdir(parents=True)
    settings.assessment_prompts_folder.mkdir(parents=True)
    prompt_path = settings.assessment_prompts_folder / "assessment-v0002.txt"
    prompt_bytes = PROMPT_TEXT.encode("utf-8")
    prompt_path.write_bytes(prompt_bytes)

    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    with database.session() as session:
        document_a = ReferenceAsset(
            asset_key="document-a",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document A",
            version=3,
            file_path="document_a/document-a-v0003.docx",
            file_hash=DOCUMENT_A_HASH,
            is_active=True,
            processing_status=ReferenceAssetProcessingStatus.READY,
            openai_file_id="file_document_a_v3",
        )
        document_b = ReferenceAsset(
            asset_key="document-b",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document B",
            version=4,
            file_path="document_b/document-b-v0004.docx",
            file_hash=DOCUMENT_B_HASH,
            is_active=True,
            processing_status=ReferenceAssetProcessingStatus.READY,
            openai_file_id="file_document_b_v4",
        )
        prompt = ReferenceAsset(
            asset_key="assessment",
            asset_type=ReferenceAssetType.PROMPT,
            name="Assessment prompt",
            version=2,
            file_path="prompts/assessment/assessment-v0002.txt",
            file_hash=sha256_file_hash(prompt_bytes),
            is_active=True,
            processing_status=ReferenceAssetProcessingStatus.READY,
        )
        session.add_all(
            [
                document_a,
                document_b,
                prompt,
            ]
        )
        session.flush()
        routing_set = DocumentBRoutingSet(
            reference_asset_id=document_b.id,
            routing_config_version="routing-v4",
            routing_config_sha256=ROUTING_HASH,
            document_b_file_sha256=DOCUMENT_B_HASH,
            extracted_section_catalog_sha256=CATALOG_HASH,
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
                for lane in LANES
            ]
        )
        job = Job(
            company="Example Company",
            job_title="Director of Architecture",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Lead the complete architecture function.\nPreserve this line exactly.",
            date_added=date(2026, 7, 29),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    try:
        yield database, settings, job_id
    finally:
        database.dispose()


def test_builds_exact_ordered_request_and_traceability(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup

    context = AssessmentContextBuilder(database, settings).build(job_id)

    assert [item.section for item in context.input] == [
        "assessment_instructions",
        "response_schema",
        "document_a",
        "job_metadata",
        "job_description",
    ]
    assert context.input[0].text == PROMPT_TEXT
    assert context.input[2].file_id == "file_document_a_v3"
    assert context.input[4].text == (
        "Lead the complete architecture function.\nPreserve this line exactly."
    )
    assert json.loads(context.input[3].text) == {
        "company": "Example Company",
        "job_title": "Director of Architecture",
        "language": "EN",
        "location": "UK",
    }
    assert context.traceability.document_a_version == 3
    assert context.traceability.document_a_hash == DOCUMENT_A_HASH
    assert context.traceability.prompt_version == 2
    assert context.traceability.schema_version == ASSESSMENT_SCHEMA_VERSION
    assert context.traceability.model_identifier == "gpt-test"
    assert context.traceability.reasoning_effort == "medium"
    assert context.reasoning_effort == "medium"
    assert context.traceability.routing_config_version == "routing-v4"
    assert context.response_schema["properties"]["primary_role_family"]["enum"] == list(LANES)


def test_keeps_stable_prefix_and_cache_identity_identical_across_jobs(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, first_job_id = context_setup
    with database.session() as session:
        second_job = Job(
            company="Another Company",
            job_title="AI Platform Lead",
            location=Location.FR,
            language=Language.FR,
            source="Company website",
            job_description="Build a new AI platform.",
            date_added=date(2026, 7, 30),
        )
        session.add(second_job)
        session.flush()
        second_job_id = second_job.id

    builder = AssessmentContextBuilder(database, settings)
    first = builder.build(first_job_id)
    second = builder.build(second_job_id)

    assert first.stable_prefix == second.stable_prefix
    assert first.cache_identity == second.cache_identity
    assert first.job_content != second.job_content


def test_cache_identity_contains_no_private_context_content(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup

    context = AssessmentContextBuilder(database, settings).build(job_id)
    rendered_identity = context.cache_identity.model_dump_json()

    assert PROMPT_TEXT.strip() not in rendered_identity
    assert "Example Company" not in rendered_identity
    assert "Lead the complete architecture function" not in rendered_identity
    assert "file_document_a_v3" not in rendered_identity
    assert len(context.cache_identity.identity_hash) == 64


def test_rendered_request_contains_no_document_b_content_or_file_identifier(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup

    rendered = AssessmentContextBuilder(database, settings).build(job_id).rendered_json()

    assert "file_document_a_v3" in rendered
    assert "file_document_b_v4" not in rendered
    assert DOCUMENT_B_HASH not in rendered
    assert "ordered_route_json" not in rendered


def test_explicit_model_overrides_configured_model(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup

    context = AssessmentContextBuilder(database, settings).build(
        job_id,
        model_identifier="  gpt-explicit  ",
    )

    assert context.traceability.model_identifier == "gpt-explicit"
    assert context.cache_identity.model_identifier == "gpt-explicit"


def test_explicit_reasoning_effort_overrides_configured_effort(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup

    context = AssessmentContextBuilder(database, settings).build(
        job_id,
        reasoning_effort="high",
    )

    assert context.reasoning_effort == "high"
    assert context.traceability.reasoning_effort == "high"


def test_missing_model_stops_context_build_clearly(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup
    settings_without_model = settings.model_copy(update={"assessment_model": None})

    with pytest.raises(AssessmentContextError, match="JAC_ASSESSMENT_MODEL"):
        AssessmentContextBuilder(database, settings_without_model).build(job_id)


def test_missing_active_document_a_stops_context_build_clearly(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup
    with database.session() as session:
        document_a = session.query(ReferenceAsset).filter_by(asset_key="document-a").one()
        document_a.is_active = False

    with pytest.raises(AssessmentContextError, match="No active Document A"):
        AssessmentContextBuilder(database, settings).build(job_id)


def test_missing_active_prompt_stops_context_build_clearly(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup
    with database.session() as session:
        prompt = session.query(ReferenceAsset).filter_by(asset_key="assessment").one()
        prompt.is_active = False

    with pytest.raises(AssessmentContextError, match="has no active version"):
        AssessmentContextBuilder(database, settings).build(job_id)


def test_missing_validated_routing_stops_context_build_clearly(
    context_setup: tuple[Database, AppSettings, int],
) -> None:
    database, settings, job_id = context_setup
    with database.session() as session:
        routing_set = session.query(DocumentBRoutingSet).one()
        routing_set.is_current = False
        routing_set.status = DocumentBRoutingSetStatus.SUPERSEDED

    with pytest.raises(AssessmentContextError, match="no current validated routing set"):
        AssessmentContextBuilder(database, settings).build(job_id)
