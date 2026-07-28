"""Strict, supplementary retrieval from section-derived Document B records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    DocumentBRetrievalRequest,
    DocumentBRetrievedPassage,
    RouteDeliveryMode,
)
from job_application_copilot.errors import ExternalServiceError
from job_application_copilot.llm import (
    OpenAIClientError,
    OpenAIVectorStoreOperations,
    OpenAIVectorStoreSearchResult,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.document_b_retrieval_repository import (
    DocumentBRetrievalRepository,
)
from job_application_copilot.repositories.models.document_b_retrieval import (
    DocumentBRetrievalTrace,
    DocumentBRetrievalTraceResult,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.document_b_routing import (
    DocumentBRoutingManifestService,
    ResolvedRouting,
)


class DocumentBRetrievalError(ExternalServiceError):
    """An actionable vector-store failure that leaves deterministic routing intact."""

    def __init__(self, message: str, *, routing: ResolvedRouting) -> None:
        self.routing = routing
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class DocumentBRetrievalPacket:
    routing: ResolvedRouting
    query: str
    passages: tuple[DocumentBRetrievedPassage, ...]


class DocumentBRetrievalService:
    """Search only verified records explicitly authorised by an existing route packet."""

    def __init__(
        self,
        database: Database,
        routing_service: DocumentBRoutingManifestService,
        client: OpenAIVectorStoreOperations,
    ) -> None:
        self.database = database
        self.routing_service = routing_service
        self.client = client

    def retrieve(self, request: DocumentBRetrievalRequest) -> DocumentBRetrievalPacket:
        routing = self.routing_service.resolve(request.document_b_version, request.lane)
        query = _build_query(request)
        authorised = tuple(
            section_id
            for entry in routing.packet.entries
            if entry.delivery_mode
            in (RouteDeliveryMode.VECTOR_SCOPE_REQUIRED, RouteDeliveryMode.VECTOR_SCOPE_OPTIONAL)
            for section_id in entry.expanded_section_ids
        )
        if not authorised:
            return DocumentBRetrievalPacket(routing=routing, query=query, passages=())

        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(
                DOCUMENT_B_KEY, request.document_b_version
            )
            vector_store_id = asset.openai_vector_store_id
            reference_asset_id = asset.id
        if vector_store_id is None:
            raise DocumentBRetrievalError(
                f"Document B version {request.document_b_version} has no vector store.",
                routing=routing,
            )

        try:
            returned = self.client.search_vector_store(
                vector_store_id=vector_store_id,
                query=query,
                max_num_results=request.result_limit,
                filters=_authorisation_filter(request.document_b_version, authorised),
            )
        except OpenAIClientError as error:
            raise DocumentBRetrievalError(str(error), routing=routing) from error

        passages = self._verified_passages(reference_asset_id, request, authorised, returned)
        self._record_trace(routing, reference_asset_id, query, passages)
        return DocumentBRetrievalPacket(routing=routing, query=query, passages=passages)

    def _verified_passages(
        self,
        reference_asset_id: int,
        request: DocumentBRetrievalRequest,
        authorised: tuple[str, ...],
        returned: tuple[OpenAIVectorStoreSearchResult, ...],
    ) -> tuple[DocumentBRetrievedPassage, ...]:
        candidates: list[DocumentBRetrievedPassage] = []
        with self.database.session() as session:
            repository = DocumentBRetrievalRepository(session)
            for result in returned:
                metadata = result.attributes
                section_id = str(metadata.get("section_id", ""))
                version = str(metadata.get("document_b_version", ""))
                if section_id not in authorised or version != str(request.document_b_version):
                    continue
                record = repository.get_vector_record(reference_asset_id, section_id)
                if record is None or record.openai_file_id != result.file_id:
                    continue
                text = result.text.strip()
                if not text:
                    continue
                passage_id = "sha256:" + hashlib.sha256(f"{record.id}:{text}".encode()).hexdigest()
                candidates.append(
                    DocumentBRetrievedPassage(
                        passage_id=passage_id,
                        text=text,
                        section_id=section_id,
                        document_b_version=request.document_b_version,
                        score=result.score,
                        source_record_id=record.id,
                        source_metadata={str(key): str(value) for key, value in metadata.items()},
                    )
                )
        return _deduplicate(candidates, request.result_limit)

    def _record_trace(
        self,
        routing: ResolvedRouting,
        reference_asset_id: int,
        query: str,
        passages: tuple[DocumentBRetrievedPassage, ...],
    ) -> None:
        with self.database.session() as session:
            trace = DocumentBRetrievalTrace(
                reference_asset_id=reference_asset_id,
                routing_set_id=routing.summary.routing_set_id,
                query_text=query,
                routing_config_version=routing.summary.routing_config_version,
            )
            results = [
                DocumentBRetrievalTraceResult(
                    vector_record_id=passage.source_record_id,
                    passage_id=passage.passage_id,
                    score=passage.score,
                    passage_text=passage.text,
                    source_metadata_json=json.dumps(passage.source_metadata, sort_keys=True),
                )
                for passage in passages
            ]
            DocumentBRetrievalRepository(session).add_trace(trace, results)


def _build_query(request: DocumentBRetrievalRequest) -> str:
    values = [
        ("Job requirements", request.job_requirements),
        ("Primary lane", request.lane.value),
        ("Evidence anchors", "; ".join(request.evidence_anchors)),
        ("Secondary lanes", "; ".join(lane.value for lane in request.secondary_lanes)),
        ("Strengths", "; ".join(request.strengths)),
        ("Gaps", "; ".join(request.gaps)),
        ("Do not overclaim", "; ".join(request.overclaiming_exclusions)),
    ]
    return "\n".join(f"{label}: {value}" for label, value in values if value)


def _authorisation_filter(version: int, section_ids: tuple[str, ...]) -> dict[str, object]:
    return {
        "type": "and",
        "filters": [
            {"type": "eq", "key": "document_b_version", "value": str(version)},
            {"type": "in", "key": "section_id", "value": list(section_ids)},
        ],
    }


def _deduplicate(
    candidates: list[DocumentBRetrievedPassage], limit: int
) -> tuple[DocumentBRetrievedPassage, ...]:
    ordered = sorted(candidates, key=lambda item: (-item.score, item.section_id, item.passage_id))
    kept: list[DocumentBRetrievedPassage] = []
    normalised: list[set[str]] = []
    for candidate in ordered:
        tokens = set(re.findall(r"\w+", candidate.text.lower()))
        if not tokens:
            continue
        if any(
            len(tokens & previous) / min(len(tokens), len(previous)) >= 0.9
            for previous in normalised
        ):
            continue
        kept.append(candidate)
        normalised.append(tokens)
        if len(kept) == limit:
            break
    return tuple(kept)
