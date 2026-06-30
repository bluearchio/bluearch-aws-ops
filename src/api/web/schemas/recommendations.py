"""Pydantic schemas for recommendation endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class RecommendationNoteResponse(BaseModel):
    id: str
    recommendation_id: str
    body: str
    author: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreateRecommendationNoteRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)
    # Optional override for the author field. When omitted the endpoint
    # falls back to the current authenticated user.
    author: Optional[str] = Field(default=None, max_length=255)


class UpdateRecommendationNoteRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unique_id: str
    recommendation_type: str
    region_name: str
    account_id: str
    account_name: Optional[str] = None
    last_updated: Optional[datetime] = None
    attributes: Optional[Dict[str, Any]] = None
    resource_id: Optional[str] = None
    # Embedded so the dashboard doesn't need a second fetch per row.
    notes: List[RecommendationNoteResponse] = []


class RecommendationTypeCount(BaseModel):
    recommendation_type: str
    count: int


class RecommendationSummaryResponse(BaseModel):
    total: int = 0
    by_type: List[RecommendationTypeCount] = []
    by_account: List[Dict[str, Any]] = []
    by_region: List[Dict[str, Any]] = []
