"""Resource browsing endpoints proxied to bluearch-core."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query

from utils.core_client import request_core
from web.schemas.common import PaginatedResponse
from web.schemas.resources import ResourceResponse, ResourceSummaryResponse

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])


@router.get("/summary", response_model=ResourceSummaryResponse)
async def resource_summary():
    """Return resource summary from the core-owned inventory."""
    try:
        return request_core("GET", "/api/v1/resources/summary", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core resource summary unavailable: {exc}") from exc


@router.get("", response_model=PaginatedResponse[ResourceResponse])
async def list_resources(
    search: Optional[str] = Query(None, description="Search by ARN or resource ID"),
    service_name: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """Return resources from the core-owned inventory."""
    params = {
        "search": search,
        "service_name": service_name,
        "region": region,
        "account_id": account_id,
        "resource_type": resource_type,
        "page": page,
        "page_size": page_size,
    }
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    suffix = f"?{query}" if query else ""
    try:
        return request_core("GET", f"/api/v1/resources{suffix}", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core resources unavailable: {exc}") from exc


@router.get("/{resource_id}")
async def get_resource(resource_id: str):
    """Return one core resource plus linked BlueArch recommendations."""
    try:
        data = request_core("GET", f"/api/v1/resources/{resource_id}", timeout=5.0)
        records = request_core(
            "GET",
            f"/api/v1/storage/bluearch/recommendations?{urlencode({'limit': 5000, 'filter': f'resource_id={resource_id}'})}",
            service_token=True,
            timeout=10.0,
        )
        data["recommendations"] = [record.get("payload", {}) for record in records]
        return data
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core resource unavailable: {exc}") from exc
