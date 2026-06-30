"""Infrastructure endpoints proxied to bluearch-core.

Shared schema structure with Tag Manager CLI so frontend views can be
identical across both apps.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from utils.core_client import request_core
from web.dependencies import get_current_user
from web.schemas.infrastructure import InfrastructureStatusResponse, ResourceGroupInfo

router = APIRouter(prefix="/api/v1/infrastructure", tags=["infrastructure"])

VALID_COMPONENTS = {"cross-account", "management-resources", "assume-role", "cost-reports"}


def _core_request(method: str, path: str, **kwargs: Any) -> Any:
    try:
        return request_core(method, path, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core infrastructure unavailable: {exc}") from exc


def _core_post(path: str, payload: dict[str, Any] | None = None) -> Any:
    return _core_request(
        "POST",
        path,
        service_token=True,
        timeout=30.0,
        json=payload or {},
    )


@router.get("/status", response_model=InfrastructureStatusResponse)
async def get_infrastructure_status(
    current_user=Depends(get_current_user),
):
    """Get unified infrastructure status from bluearch-core."""
    result = _core_request("GET", "/api/v1/infrastructure/status", timeout=30.0)
    return result


@router.post("/resource-group/create", response_model=ResourceGroupInfo)
async def create_resource_group(
    _request: Request,
    _user=Depends(get_current_user),
):
    """Create or update the shared Resource Group through bluearch-core."""
    return _core_post("/api/v1/infrastructure/resource-group/create")


@router.post("/resource-group/delete")
async def delete_resource_group(
    _request: Request,
    _user=Depends(get_current_user),
):
    """Delete the shared Resource Group through bluearch-core."""
    return _core_post("/api/v1/infrastructure/resource-group/delete")


@router.post("/cur-stack/delete")
async def delete_cur_stack(
    _request: Request,
    _user=Depends(get_current_user),
):
    """Delete the CUR stack through bluearch-core."""
    return _core_post("/api/v1/infrastructure/cur-stack/delete")


@router.post("/stacks/cost-reports/deploy")
async def deploy_cur_stack(
    _request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    _user=Depends(get_current_user),
):
    """Deploy the CUR stack through bluearch-core."""
    return _core_post("/api/v1/infrastructure/stacks/cost-reports/deploy", payload)


@router.post("/stacks/{component}/update")
async def update_infrastructure_stack(
    _request: Request,
    component: str,
    _user=Depends(get_current_user),
):
    """Update a deployed infrastructure stack through bluearch-core."""
    if component not in VALID_COMPONENTS:
        raise HTTPException(status_code=400, detail=f"Unknown component: {component}")
    return _core_post(f"/api/v1/infrastructure/stacks/{component}/update")

