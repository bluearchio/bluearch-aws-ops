"""Scan endpoints proxied to bluearch-core."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Query

from utils.core_client import request_core
from web.schemas.scans import ScanHistoryResponse, ScanJobResponse, ScanRequest

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])

APP_SOURCE = "bluearch"


def _core_scan_payload(body: ScanRequest) -> dict:
    return {
        "product": APP_SOURCE,
        "services": body.services or [],
        "regions": body.regions or [],
    }


def _start_response(row: dict) -> ScanJobResponse:
    return ScanJobResponse(
        job_id=row.get("id") or row.get("job_id") or "",
        status=row.get("status") or "pending",
        message=row.get("message") or row.get("progress_message") or "Scan queued",
    )


@router.post("", response_model=ScanJobResponse)
async def start_scan(body: ScanRequest):
    """Queue a core-owned inventory scan."""
    try:
        return _start_response(
            request_core(
                "POST",
                "/api/v1/scans",
                json=_core_scan_payload(body),
                timeout=10.0,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan submission unavailable: {exc}") from exc


@router.post("/jobs/{job_id}/cancel")
async def cancel_scan_job(job_id: str):
    """Cancel a core-owned scan job."""
    try:
        return request_core("POST", f"/api/v1/scans/jobs/{job_id}/cancel", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan cancellation unavailable: {exc}") from exc


@router.get("/jobs")
async def list_scan_jobs():
    """List core-owned scan jobs."""
    try:
        return request_core("GET", "/api/v1/scans/jobs", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan jobs unavailable: {exc}") from exc


@router.get("/jobs/{job_id}")
async def get_scan_job(job_id: str):
    """Get a core-owned scan job."""
    try:
        return request_core("GET", f"/api/v1/scans/jobs/{job_id}", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan job unavailable: {exc}") from exc


@router.get("/history", response_model=List[ScanHistoryResponse])
async def scan_history(limit: int = Query(20, ge=1, le=100)):
    """Return completed core-owned scan jobs in the legacy history shape."""
    try:
        rows = request_core("GET", "/api/v1/scans/history", timeout=5.0) or []
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan history unavailable: {exc}") from exc
    items = []
    for row in rows[:limit]:
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        items.append(
            {
                "id": row.get("id"),
                "scan_mode": ",".join(row.get("services") or []) or "all",
                "collected_by": row.get("source") or row.get("product") or APP_SOURCE,
                "started_at": row.get("started_at"),
                "completed_at": row.get("completed_at"),
                "status": row.get("status") or "unknown",
                "resources_found": result.get("resources_found") or row.get("total_resources") or 0,
                "error_message": row.get("error"),
            }
        )
    return items


def cancel_orphaned_scan_jobs() -> int:
    """Compatibility hook retained for routers that used to clean local rows."""
    return 0
