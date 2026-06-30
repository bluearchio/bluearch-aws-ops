"""Unified system endpoints backed by bluearch-core."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from aws.misc.version_controller import CURRENT_VERSION
from utils.event_hooks import track_event
from utils.core_client import request_core
from web.dependencies import get_current_user
from web.routers.setup import SetupValidateResponse, get_iam_policy, validate_setup

router = APIRouter(tags=["system"])


@router.get("/api/v1/system/health")
async def health_check():
    """Fast readiness check for the local product server and core dependency."""
    try:
        core_health = request_core("GET", "/api/v1/core/health", timeout=1.0)
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


@router.get("/api/v1/system/stats")
async def system_stats(current_user=Depends(get_current_user)):
    """Dashboard summary statistics from bluearch-core."""
    try:
        resource_summary = request_core("GET", "/api/v1/resources/summary", timeout=5.0)
        recommendations = request_core("GET", "/api/v1/storage/bluearch/recommendations?limit=1", service_token=True, timeout=5.0)
        accounts = request_core("GET", "/api/v1/accounts", timeout=5.0)
        jobs = request_core("GET", "/api/v1/jobs", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core system stats unavailable: {exc}") from exc
    active_jobs = [job for job in jobs if job.get("status") in {"pending", "running", "cancelling"}]
    try:
        track_event(
            "web.system.stats",
            properties={"user_sub": getattr(current_user, "sub", None), "count": resource_summary.get("total", 0), "source": "bluearch-core"},
        )
    except Exception:
        pass
    return {
        "resources": resource_summary.get("total", 0),
        "recommendations": len(recommendations),
        "accounts": len(accounts),
        "last_scan": None,
        "active_jobs": len(active_jobs),
        "cache_size_mb": 0.0,
    }


@router.get("/api/v1/system/setup/validate", response_model=SetupValidateResponse)
async def system_validate_setup(_user: Optional[dict] = Depends(get_current_user)):
    """Alias for /api/v1/setup/validate."""
    return await validate_setup(_user=_user)


@router.get("/api/v1/system/setup/iam-policy")
async def system_iam_policy(_user: Optional[dict] = Depends(get_current_user)):
    """Alias for /api/v1/setup/iam-policy."""
    return await get_iam_policy(_user=_user)


@router.get("/api/v1/system/permissions")
async def system_permissions(_user: Optional[dict] = Depends(get_current_user)):
    """Return core-owned permission tier and feature availability."""
    try:
        return request_core("GET", "/api/v1/system/permissions", timeout=5.0)
    except Exception:
        try:
            from web.routers.license import get_license

            license_info = await get_license(current_user=_user)
            features = license_info.get("features") or {}
            tier = str(license_info.get("tier") or "free").lower()
            if isinstance(features, list):
                feature_map = {name: {"available": True} for name in features}
            else:
                feature_map = {str(name): {"available": bool(allowed)} for name, allowed in dict(features).items()}
            return {
                "account_id": license_info.get("account_id"),
                "tier": tier,
                "features": feature_map,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"permission status unavailable: {exc}") from exc


@router.post("/api/v1/system/permissions/refresh")
async def refresh_system_permissions(_user: Optional[dict] = Depends(get_current_user)):
    """Refresh and return permission status."""
    try:
        return request_core(
            "POST",
            "/api/v1/system/permissions/refresh",
            service_token=True,
            timeout=10.0,
        )
    except Exception:
        return await system_permissions(_user=_user)
