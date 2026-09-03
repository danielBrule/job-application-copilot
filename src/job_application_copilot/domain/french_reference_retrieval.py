"""Validated style-only French reference retrieval values."""

from pydantic import BaseModel, ConfigDict, Field


class FrenchReferenceRetrievalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1)
    result_limit: int = Field(default=5, ge=1, le=20)


class FrenchReferencePassage(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    score: float
    reference_asset_id: int
    asset_key: str
    version: int
    name: str
    style_reference_only: bool = True
    source_metadata: dict[str, str]
