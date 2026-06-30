"""Core-backed local notification feed."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from utils.core_client import request_core

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    refresh: bool = Query(False),
):
    try:
        return request_core(
            "GET",
            f"/api/v1/notifications?limit={limit}&refresh={str(refresh).lower()}",
            timeout=30.0,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"bluearch-core notifications unavailable: {exc}",
        ) from exc
