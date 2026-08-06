"""Tests for strict supplementary retrieval within a resolved Document B route."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import install_document_b_routing_config, make_routable_document_b

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import DocumentBRetrievalRequest, ReferenceAssetType
from job_application_copilot.llm import OpenAIVectorStoreSearchResult
from job_application_copilot.repositories import create_database
from job_application_copilot.repositories.document_b_retrieval_repository import (
    DocumentBRetrievalRepository,
)
from job_application_copilot.repositories.models import (
    DocumentBRetrievalTrace,
    DocumentBRetrievalTraceResult,
    DocumentBVectorRecord,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DocumentBRetrievalError,
    DocumentBRetrievalService,
    DocumentBRoutingManifestService,
    DocumentBSectionService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


def make_context(tmp_path: Path) -> tuple[object, DocumentBRoutingManifestService, int]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    install_document_b_routing_config(settings)
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    storage = ReferenceAssetStorageService(database, settings)
    version = storage.store(
        filename="document-b.docx",
        content=make_routable_document_b(),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    ).version
    routing = DocumentBRoutingManifestService(database, DocumentBSectionService(database, settings))
    routing.generate(version)
    with database.session() as session:
        asset = ReferenceAssetRepository(session).require_version("document-b", version)
        asset.openai_vector_store_id = "vs_document_b"
        section_id = next(
            entry.expanded_section_ids[0]
            for entry in routing.resolve(version, "HEAD_OF_SOLUTIONS_ARCHITECTURE").packet.entries
            if entry.delivery_mode.value.startswith("VECTOR_SCOPE")
        )
        DocumentBRetrievalRepository(session).add_vector_record(
            DocumentBVectorRecord(
                reference_asset_id=asset.id,
                section_id=section_id,
                content_hash="sha256:content",
                openai_file_id="file_section",
                vector_store_id="vs_document_b",
            )
        )
    return database, routing, version


def request(version: int) -> DocumentBRetrievalRequest:
    return DocumentBRetrievalRequest(
        document_b_version=version,
        lane="HEAD_OF_SOLUTIONS_ARCHITECTURE",
        job_requirements="Own applied AI architecture delivery.",
        evidence_anchors=("Led solution architecture.",),
        overclaiming_exclusions=("Do not claim sole production ownership.",),
    )


def test_retrieval_filters_and_returns_only_verified_authorised_results(tmp_path: Path) -> None:
    database, routing, version = make_context(tmp_path)
    resolved = routing.resolve(version, "HEAD_OF_SOLUTIONS_ARCHITECTURE")
    section_id = next(
        entry.expanded_section_ids[0]
        for entry in resolved.packet.entries
        if entry.delivery_mode.value.startswith("VECTOR_SCOPE")
    )
    client = Mock()
    client.search_vector_store.return_value = (
        OpenAIVectorStoreSearchResult(
            file_id="file_section",
            filename="section.txt",
            score=0.9,
            text="Verified optional positioning passage.",
            attributes={"document_b_version": str(version), "section_id": section_id},
        ),
        OpenAIVectorStoreSearchResult(
            file_id="file_unknown",
            filename="other.txt",
            score=1.0,
            text="Must be rejected.",
            attributes={"document_b_version": str(version), "section_id": section_id},
        ),
    )

    packet = DocumentBRetrievalService(database, routing, client).retrieve(request(version))

    assert [passage.text for passage in packet.passages] == [
        "Verified optional positioning passage."
    ]
    assert packet.routing == resolved
    assert any(
        entry.delivery_mode.value == "DIRECT_CONTEXT" for entry in packet.routing.packet.entries
    )
    filters = client.search_vector_store.call_args.kwargs["filters"]
    assert filters["filters"][0]["value"] == str(version)
    assert section_id in filters["filters"][1]["value"]

    with database.session() as session:
        trace = session.query(DocumentBRetrievalTrace).one()
        trace_result = session.query(DocumentBRetrievalTraceResult).one()

    assert trace.reference_asset_id > 0
    assert trace.routing_set_id == resolved.summary.routing_set_id
    assert trace.routing_config_version == resolved.summary.routing_config_version
    assert trace.query_text == packet.query
    assert trace_result.passage_id == packet.passages[0].passage_id
    assert trace_result.score == packet.passages[0].score
    assert trace_result.passage_text == packet.passages[0].text
    assert json.loads(trace_result.source_metadata_json) == packet.passages[0].source_metadata


def test_retrieval_deduplicates_and_limits_verified_top_chunks(tmp_path: Path) -> None:
    database, routing, version = make_context(tmp_path)
    resolved = routing.resolve(version, "HEAD_OF_SOLUTIONS_ARCHITECTURE")
    section_ids = [
        entry.expanded_section_ids[0]
        for entry in resolved.packet.entries
        if entry.delivery_mode.value.startswith("VECTOR_SCOPE")
    ]
    first_section_id, second_section_id = section_ids[:2]
    with database.session() as session:
        asset = ReferenceAssetRepository(session).require_version("document-b", version)
        DocumentBRetrievalRepository(session).add_vector_record(
            DocumentBVectorRecord(
                reference_asset_id=asset.id,
                section_id=second_section_id,
                content_hash="sha256:second-content",
                openai_file_id="file_second_section",
                vector_store_id="vs_document_b",
            )
        )

    client = Mock()
    client.search_vector_store.return_value = (
        OpenAIVectorStoreSearchResult(
            file_id="file_section",
            filename="first.txt",
            score=0.99,
            text="Led applied AI architecture delivery for regulated clients.",
            attributes={"document_b_version": str(version), "section_id": first_section_id},
        ),
        OpenAIVectorStoreSearchResult(
            file_id="file_section",
            filename="first.txt",
            score=0.95,
            text="Led applied AI architecture delivery for regulated clients successfully.",
            attributes={"document_b_version": str(version), "section_id": first_section_id},
        ),
        OpenAIVectorStoreSearchResult(
            file_id="file_second_section",
            filename="second.txt",
            score=0.80,
            text="Built data-product operating models with measurable commercial outcomes.",
            attributes={"document_b_version": str(version), "section_id": second_section_id},
        ),
        OpenAIVectorStoreSearchResult(
            file_id="file_second_section",
            filename="second.txt",
            score=0.70,
            text="Established cross-functional delivery governance for complex programmes.",
            attributes={"document_b_version": str(version), "section_id": second_section_id},
        ),
    )

    packet = DocumentBRetrievalService(database, routing, client).retrieve(
        request(version).model_copy(update={"result_limit": 2})
    )

    assert [passage.score for passage in packet.passages] == [0.99, 0.80]
    assert [passage.section_id for passage in packet.passages] == [
        first_section_id,
        second_section_id,
    ]


def test_missing_or_mismatched_provenance_is_rejected(tmp_path: Path) -> None:
    database, routing, version = make_context(tmp_path)
    client = Mock()
    client.search_vector_store.return_value = (
        OpenAIVectorStoreSearchResult(
            file_id="file_section",
            filename="section.txt",
            score=0.9,
            text="Wrong version.",
            attributes={"document_b_version": "999", "section_id": "unknown"},
        ),
    )

    assert (
        DocumentBRetrievalService(database, routing, client).retrieve(request(version)).passages
        == ()
    )


def test_vector_failure_preserves_resolved_routing(tmp_path: Path) -> None:
    database, routing, version = make_context(tmp_path)
    client = Mock()
    from job_application_copilot.llm import OpenAIClientError

    client.search_vector_store.side_effect = OpenAIClientError(
        "OpenAI could not be reached.", operation="vector_store_search", retryable=True
    )

    with pytest.raises(DocumentBRetrievalError) as raised:
        DocumentBRetrievalService(database, routing, client).retrieve(request(version))

    assert raised.value.routing == routing.resolve(version, "HEAD_OF_SOLUTIONS_ARCHITECTURE")
