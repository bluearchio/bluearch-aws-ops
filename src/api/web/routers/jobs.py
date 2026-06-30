"""Job management endpoints proxied to bluearch-core."""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.event_hooks import track_event
from utils.core_client import request_core
from web.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

APP_SOURCE = "bluearch"


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    progress: int = 0
    progress_message: Optional[str] = None
    progress_data: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ScanJobRequest(BaseModel):
    services: Optional[List[str]] = None
    regions: Optional[List[str]] = None


class DeleteJobRequest(BaseModel):
    services: Optional[List[str]] = None


class JobSubmittedResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    message: str


def _core_get(path: str):
    return request_core("GET", path, timeout=5.0)


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    job_type: Optional[str] = None,
    current_user=Depends(get_current_user),
) -> list[dict]:
    """List core-owned jobs, optionally filtered by type."""
    query = f"?{urlencode({'job_type': job_type})}" if job_type else ""
    try:
        result = _core_get(f"/api/v1/jobs{query}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core jobs unavailable: {exc}") from exc
    try:
        track_event("web.jobs.list", properties={"user_sub": getattr(current_user, "sub", None), "count": len(result)})
    except Exception:
        pass
    return result


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> dict:
    """Get a core-owned job."""
    try:
        return _core_get(f"/api/v1/jobs/{job_id}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core job unavailable: {exc}") from exc


@router.post("/scan", response_model=JobSubmittedResponse)
async def submit_scan_job(
    request: ScanJobRequest,
    _user: Optional[dict] = Depends(get_current_user),
) -> JobSubmittedResponse:
    """Submit a resource scan job to bluearch-core."""
    try:
        job = request_core(
            "POST",
            "/api/v1/scans",
            json={"product": APP_SOURCE, "services": request.services or [], "regions": request.regions or []},
            timeout=10.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan submission unavailable: {exc}") from exc
    svc_label = f" ({', '.join(request.services)})" if request.services else ""
    return JobSubmittedResponse(
        job_id=job.get("id") or job.get("job_id") or "",
        job_type="scan",
        status=job.get("status") or "pending",
        message=f"Resource scan started{svc_label}",
    )


@router.post("/delete", response_model=JobSubmittedResponse)
async def submit_delete_job(
    _request: DeleteJobRequest,
    _user: Optional[dict] = Depends(get_current_user),
) -> JobSubmittedResponse:
    """Deprecated local DB cleanup job.

    Resource inventory is core-owned now; stale-resource deletion must be
    implemented as a core job before this endpoint can mutate anything.
    """
    raise HTTPException(status_code=501, detail="Resource cleanup jobs must run through bluearch-core")
