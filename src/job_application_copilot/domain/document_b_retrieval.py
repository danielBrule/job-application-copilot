"""Validated values exchanged by section-aware Document B retrieval."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from job_application_copilot.domain.document_b_routing import LaneId


class DocumentBRetrievalRequest(BaseModel):
    """Phase 2 inputs permitted to shape a supplementary retrieval query."""

    model_config = ConfigDict(frozen=True)

    document_b_version: int = Field(gt=0)
    lane: LaneId
    job_requirements: str = Field(min_length=1)
    evidence_anchors: tuple[str, ...] = ()
    secondary_lanes: tuple[LaneId, ...] = ()
    strengths: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    overclaiming_exclusions: tuple[str, ...] = ()
    result_limit: int = Field(default=8, ge=1, le=50)


class DocumentBRetrievedPassage(BaseModel):
    model_config = ConfigDict(frozen=True)

    passage_id: str
    text: str
    section_id: str
    document_b_version: int
    score: float
    source_record_id: int
    source_metadata: dict[str, str]
