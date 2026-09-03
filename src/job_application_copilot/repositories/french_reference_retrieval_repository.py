"""Persistence operations for French style-reference indexing and lookup."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.repositories.models.french_reference_retrieval import (
    FrenchReferenceVectorSource,
    FrenchReferenceVectorStore,
)


class FrenchReferenceRetrievalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_store(self) -> FrenchReferenceVectorStore | None:
        return self.session.get(FrenchReferenceVectorStore, 1)

    def add_store(self, vector_store_id: str) -> FrenchReferenceVectorStore:
        store = FrenchReferenceVectorStore(id=1, vector_store_id=vector_store_id)
        self.session.add(store)
        self.session.flush()
        return store

    def get_source(self, reference_asset_id: int) -> FrenchReferenceVectorSource | None:
        return self.session.scalar(
            select(FrenchReferenceVectorSource).where(
                FrenchReferenceVectorSource.reference_asset_id == reference_asset_id
            )
        )

    def add_source(self, source: FrenchReferenceVectorSource) -> FrenchReferenceVectorSource:
        self.session.add(source)
        self.session.flush()
        return source
