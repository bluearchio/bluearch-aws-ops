"""Assume-role management endpoints proxied to bluearch-core."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.event_hooks import track_event
from utils.core_client import request_core
from web.dependencies import get_current_user
from web.schemas.assume_role import AddAssumeRoleRequest, AssumeRoleConfigResponse, TestResultResponse

router = APIRouter(prefix="/api/v1/assume-role", tags=["assume-role"])

DEFAULT_ROLE_NAME = "BlueArchCLIRole"


class AssumeRoleStatusResponse(BaseModel):
    configured: bool = False
    enabled: bool = False
    role_arn: Optional[str] = None
    role_name: Optional[str] = None
    account_id: Optional[str] = None
    external_id_configured: bool = False
    last_used_at: Optional[str] = None
    stack_exists: bool = False
    stack_status: Optional[str] = None


class AssumeRoleDeployRequest(BaseModel):
    trust_mode: str = Field("AnyPrincipal", description="Trust policy mode: AnyPrincipal, CurrentUser, or SpecificArn")
    specific_arn: Optional[str] = Field(None, description="IAM ARN when trust_mode is SpecificArn")
    external_id: Optional[str] = Field(None, description="External ID for role assumption (optional)")
    role_name: str = Field("BlueArchCLIRole", description="Name of the IAM role to create")


class AssumeRoleDisableRequest(BaseModel):
    delete_stack: bool = Field(False, description="Also delete the CloudFormation stack")


class JobSubmittedResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    message: str


def _payload(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _submitted(row: dict, job_type: str, message: str) -> JobSubmittedResponse:
    return JobSubmittedResponse(
        job_id=row.get("id") or row.get("job_id") or "",
        job_type=row.get("job_type") or job_type,
        status=row.get("status") or "pending",
        message=row.get("message") or message,
    )


@router.get("/status", response_model=AssumeRoleStatusResponse)
async def assume_role_status(_user=Depends(get_current_user)):
    """Get current assume-role configuration and CloudFormation stack status."""
    try:
        return request_core("GET", "/api/v1/assume-role/status", timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role status unavailable: {exc}") from exc


@router.get("/configs", response_model=List[AssumeRoleConfigResponse])
async def list_configs(current_user=Depends(get_current_user)):
    """List assume-role configurations from bluearch-core."""
    try:
        result = request_core("GET", "/api/v1/assume-role/configs", timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role configs unavailable: {exc}") from exc
    try:
        track_event("web.assume_role.list", properties={"user_sub": getattr(current_user, "sub", None), "count": len(result), "source": "bluearch-core"})
    except Exception:
        pass
    return result


@router.post("/add", response_model=AssumeRoleConfigResponse)
async def add_config(body: AddAssumeRoleRequest, _user=Depends(get_current_user)):
    """Create a manual assume-role configuration through bluearch-core."""
    try:
        return request_core("POST", "/api/v1/assume-role/add", service_token=True, json=_payload(body), timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role add unavailable: {exc}") from exc


@router.delete("/{config_id}")
async def delete_config(config_id: str, _user=Depends(get_current_user)):
    """Delete a manual assume-role configuration through bluearch-core."""
    try:
        return request_core("DELETE", f"/api/v1/assume-role/{config_id}", service_token=True, timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role delete unavailable: {exc}") from exc


@router.post("/test/{config_id}", response_model=TestResultResponse)
async def test_config(config_id: str, _user=Depends(get_current_user)):
    """Test an assume-role configuration through bluearch-core."""
    try:
        return request_core("POST", f"/api/v1/assume-role/test/{config_id}", service_token=True, timeout=20.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role test unavailable: {exc}") from exc


@router.post("/deploy", response_model=JobSubmittedResponse)
async def deploy_assume_role(body: AssumeRoleDeployRequest, _user=Depends(get_current_user)):
    """Deploy assume-role CloudFormation through bluearch-core."""
    try:
        row = request_core("POST", "/api/v1/assume-role/deploy", service_token=True, json=_payload(body), timeout=20.0)
        return _submitted(row, "assume_role_deploy", "Assume-role deployment started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role deploy unavailable: {exc}") from exc


@router.post("/disable")
async def disable_assume_role(body: AssumeRoleDisableRequest, _user=Depends(get_current_user)):
    """Disable assume-role configuration through bluearch-core."""
    try:
        row = request_core("POST", "/api/v1/assume-role/disable", service_token=True, json=_payload(body), timeout=20.0)
        return _submitted(row, "assume_role_delete_stack" if body.delete_stack else "assume_role_disable", "Assume-role disable started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role disable unavailable: {exc}") from exc
