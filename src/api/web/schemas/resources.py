"""Pydantic schemas for resource endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class ResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resource_arn: str
    resource_type: str
    service_name: str
    region: str
    account_id: str
    resource_id: str
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    discovered_at: Optional[datetime] = None
    last_scanned_at: Optional[datetime] = None
    current_tags: Optional[Dict[str, Any]] = None
    metadata_json: Optional[Dict[str, Any]] = None
    lifecycle_state: Optional[str] = None
    expires_at: Optional[datetime] = None
    protected: Optional[bool] = None
    compliance_status: Optional[str] = None


class ResourceSummaryResponse(BaseModel):
    total: int = 0
    by_service: List[Dict[str, Any]] = []
    by_region: List[Dict[str, Any]] = []
    by_account: List[Dict[str, Any]] = []
