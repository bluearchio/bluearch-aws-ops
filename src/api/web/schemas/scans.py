"""Pydantic schemas for scan endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ScanRequest(BaseModel):
    services: Optional[List[str]] = None
    # None defaults to the fast US-region set. Pass ["all"] to scan every enabled region.
    regions: Optional[List[str]] = None


class ScanJobResponse(BaseModel):
    job_id: str
    status: str
    message: str = ""


class ScanHistoryResponse(BaseModel):
    id: str
    scan_mode: str
    collected_by: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str
    resources_found: int = 0
    error_message: Optional[str] = None
