"""Setup validation endpoints proxied to bluearch-core."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.core_client import request_core
from web.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


class SetupCheckItem(BaseModel):
    name: str
    status: str
    message: str
    details: Optional[dict] = None


class SetupValidateResponse(BaseModel):
    overall: str
    checks: list[SetupCheckItem]


def _normalize_core_validation(payload: dict) -> SetupValidateResponse:
    checks = payload.get("checks") if isinstance(payload, dict) else {}
    if isinstance(checks, list):
        statuses = [item.get("status") for item in checks if isinstance(item, dict)]
        overall = payload.get("overall") or _overall(statuses)
        return SetupValidateResponse(overall=overall, checks=checks)

    normalized = []
    if isinstance(checks, dict):
        database = checks.get("database") or {}
        normalized.append(
            SetupCheckItem(
                name="Database",
                status="ok" if database.get("ok") else "error",
                message=f"Core database ready at {database.get('path')}" if database.get("ok") else "Core database is not ready",
                details=database,
            )
        )
        aws = checks.get("aws_credentials") or {}
        identity = aws.get("identity") or {}
        normalized.append(
            SetupCheckItem(
                name="AWS Credentials",
                status="ok" if aws.get("ok") else "error",
                message=f"Authenticated as {identity.get('Arn', 'unknown')}" if aws.get("ok") else f"AWS credentials unavailable: {aws.get('error')}",
                details=aws,
            )
        )
        token = checks.get("service_token") or {}
        normalized.append(
            SetupCheckItem(
                name="BlueArch Core",
                status="ok" if token.get("ok") else "error",
                message=f"Core service token ready at {token.get('path')}" if token.get("ok") else "Core service token missing",
                details=token,
            )
        )
    statuses = [item.status for item in normalized]
    return SetupValidateResponse(overall=payload.get("overall") or _overall(statuses), checks=normalized)


def _overall(statuses: list[str]) -> str:
    if "error" in statuses:
        return "unhealthy"
    if "warning" in statuses:
        return "degraded"
    return "healthy"


@router.get("/validate", response_model=SetupValidateResponse)
async def validate_setup(_user: Optional[dict] = Depends(get_current_user)) -> SetupValidateResponse:
    """Return setup validation from the shared core runtime."""
    try:
        result = _normalize_core_validation(request_core("GET", "/api/v1/setup/validate", timeout=15.0))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core setup validation unavailable: {exc}") from exc
    return result


@router.get("/iam-policy")
async def get_iam_policy(_user: Optional[dict] = Depends(get_current_user)) -> dict:
    """Return the recommended IAM policy from bluearch-core."""
    try:
        policy = request_core("GET", "/api/v1/setup/iam-policy", timeout=10.0)
        return {"policy": policy, "source": "bluearch-core"}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core IAM policy unavailable: {exc}") from exc
