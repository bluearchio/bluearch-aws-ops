"""Pydantic schemas for the log analysis API."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    model: str = Field(default="sonnet", pattern="^(haiku|sonnet|opus)$")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class ScanSummary(BaseModel):
    id: str
    account_id: Optional[str] = None
    region: Optional[str] = None
    log_groups_scanned: int = 0
    findings_count: int = 0
    time_window_hours: int = 24
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "running"
    error_message: Optional[str] = None


class LogFindingResponse(BaseModel):
    id: str
    scan_id: Optional[str] = None
    log_group_name: Optional[str] = None
    error_pattern: Optional[str] = None
    severity: Optional[str] = None
    occurrence_count: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    sample_message: Optional[str] = None
    resource_id: Optional[str] = None
    resource_type: Optional[str] = None
    service_name: Optional[str] = None
    link_status: str = "unlinked"
    status: str = "open"
    ai_analysis: Optional[str] = None
    ai_analyzed_at: Optional[datetime] = None
    detected_at: Optional[datetime] = None


class ListFindingsResponse(BaseModel):
    items: List[LogFindingResponse]
    total: int
    page: int
    page_size: int


class AnalyzeResponse(BaseModel):
    finding_id: str
    analysis: str
    model: str
    analyzed_at: datetime
