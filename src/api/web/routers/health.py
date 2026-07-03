"""Health check endpoint backed by bluearch-core."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from aws.misc.version_controller import CURRENT_VERSION
from utils.core_client import request_core

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/health")
async def health_check():
    """Fast readiness check for the local product server and core dependency."""
    try:
        core_health = request_core("GET", "/api/v1/core/health", service_token=False, timeout=1.0)
    except Exception as exc:
        return {
            "status": "unhealthy",
            "version": CURRENT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": {"connected": False, "error": str(exc)},
            "aws": {"connected": False, "status": "not_checked"},
        }
    return {
        "status": "healthy" if core_health.get("status") == "ok" and core_health.get("db_ready") else "degraded",
        "version": CURRENT_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": {"connected": bool(core_health.get("db_ready")), "source": "bluearch-core"},
        "aws": {
            "connected": False,
            "status": "not_checked",
            "message": "Use /api/v1/setup/validate for AWS credential status.",
        },
    }
