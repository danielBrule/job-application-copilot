"""Persistence operations for generated Document B routing manifests."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import DocumentBRoutingSetStatus, LaneId
from job_application_copilot.repositories.models import (
    DocumentBLaneRoute,
    DocumentBRoutingSet,
)


class DocumentBRoutingRepository:
    """Read and write routing sets within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_set(self, routing_set: DocumentBRoutingSet) -> DocumentBRoutingSet:
        self.session.add(routing_set)
        self.session.flush()
        return routing_set

    def add_routes(self, routes: list[DocumentBLaneRoute]) -> None:
        self.session.add_all(routes)
        self.session.flush()

    def get_set(self, routing_set_id: int) -> DocumentBRoutingSet | None:
        return self.session.get(DocumentBRoutingSet, routing_set_id)

    def get_current(self, reference_asset_id: int) -> DocumentBRoutingSet | None:
        return self.session.scalar(
            select(DocumentBRoutingSet).where(
                DocumentBRoutingSet.reference_asset_id == reference_asset_id,
                DocumentBRoutingSet.is_current.is_(True),
            )
        )

    def list_for_asset(self, reference_asset_id: int) -> list[DocumentBRoutingSet]:
        return list(
            self.session.scalars(
                select(DocumentBRoutingSet)
                .where(DocumentBRoutingSet.reference_asset_id == reference_asset_id)
                .order_by(DocumentBRoutingSet.generated_at.desc(), DocumentBRoutingSet.id.desc())
            )
        )

    def get_route(self, routing_set_id: int, lane: LaneId) -> DocumentBLaneRoute | None:
        return self.session.scalar(
            select(DocumentBLaneRoute).where(
                DocumentBLaneRoute.routing_set_id == routing_set_id,
                DocumentBLaneRoute.lane_id == lane,
            )
        )

    def list_routes(self, routing_set_id: int) -> list[DocumentBLaneRoute]:
        return list(
            self.session.scalars(
                select(DocumentBLaneRoute)
                .where(DocumentBLaneRoute.routing_set_id == routing_set_id)
                .order_by(DocumentBLaneRoute.lane_id)
            )
        )

    def supersede_current(self, reference_asset_id: int) -> None:
        current = self.get_current(reference_asset_id)
        if current is not None:
            current.is_current = False
            current.status = DocumentBRoutingSetStatus.SUPERSEDED
            self.session.flush()
