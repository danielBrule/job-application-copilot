"""Persistence operations for verified Document B retrieval sources and traces."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.repositories.models.document_b_retrieval import (
    DocumentBRetrievalTrace,
    DocumentBRetrievalTraceResult,
    DocumentBVectorRecord,
)


class DocumentBRetrievalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_vector_record(
        self, reference_asset_id: int, section_id: str
    ) -> DocumentBVectorRecord | None:
        return self.session.scalar(
            select(DocumentBVectorRecord).where(
                DocumentBVectorRecord.reference_asset_id == reference_asset_id,
                DocumentBVectorRecord.section_id == section_id,
            )
        )

    def add_vector_record(self, record: DocumentBVectorRecord) -> DocumentBVectorRecord:
        self.session.add(record)
        self.session.flush()
        return record

    def add_trace(
        self, trace: DocumentBRetrievalTrace, results: list[DocumentBRetrievalTraceResult]
    ) -> None:
        self.session.add(trace)
        self.session.flush()
        for result in results:
            result.trace_id = trace.id
        self.session.add_all(results)
        self.session.flush()
