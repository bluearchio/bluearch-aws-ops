"""Account context management backed by bluearch-core."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.core_client import request_core, request_core_response
from web.dependencies import get_current_user

router = APIRouter(prefix="/api/v1", tags=["context"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SwitchContextRequest(BaseModel):
    account_id: str = Field(..., min_length=12, max_length=12)


class AddContextRequest(BaseModel):
    alias: Optional[str] = None


class AccountContextResponse(BaseModel):
    id: Optional[str] = None
    account_id: Optional[str] = None
    account_alias: Optional[str] = None
    aws_profile: Optional[str] = None
    region: Optional[str] = None
    user_arn: Optional[str] = None
    is_current: bool = False
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class ContextGateResponse(BaseModel):
    status: str  # ok, new_context, mismatch
    message: str
    context: Optional[AccountContextResponse] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/context")
async def get_current_context():
    """Return the current active context."""
    return await _get_current_context("/api/v1/context")


async def _get_current_context(path: str):
    try:
        response = request_core_response(
            "GET",
            path,
            timeout=5.0,
            raise_for_status=False,
        )
        if response.status_code == 404:
            return _empty_context()
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code} {response.text}")
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context unavailable: {exc}") from exc


@router.get("/contexts")
async def list_contexts(
    current_user=Depends(get_current_user),
):
    """List all registered contexts."""
    return await _list_contexts("/api/v1/contexts")


async def _list_contexts(path: str):
    try:
        return request_core("GET", path, timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core contexts unavailable: {exc}") from exc


@router.post("/context")
async def add_context(
    body: AddContextRequest,
    _user: Optional[dict] = Depends(get_current_user),
):
    """Register current AWS identity as a context."""
    return await _add_context("/api/v1/context", body)


async def _add_context(path: str, body: AddContextRequest):
    try:
        return request_core(
            "POST",
            path,
            service_token=True,
            json=_model_dump(body),
            timeout=10.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context registration unavailable: {exc}") from exc


@router.post("/context/switch")
async def switch_context(
    body: SwitchContextRequest,
    _user: Optional[dict] = Depends(get_current_user),
):
    """Switch active context to a different account."""
    return await _switch_context("/api/v1/context/switch", body)


async def _switch_context(path: str, body: SwitchContextRequest):
    try:
        return request_core(
            "POST",
            path,
            service_token=True,
            json=_model_dump(body),
            timeout=5.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context switch unavailable: {exc}") from exc


@router.delete("/context/{account_id}")
async def remove_context(
    account_id: str,
    _user: Optional[dict] = Depends(get_current_user),
):
    """Remove a registered context."""
    return await _remove_context("/api/v1/context", account_id)


async def _remove_context(base_path: str, account_id: str):
    try:
        return request_core(
            "DELETE",
            f"{base_path}/{account_id}",
            service_token=True,
            timeout=5.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context removal unavailable: {exc}") from exc


@router.get("/context/gate")
async def context_gate():
    """Startup gate: auto-register or detect mismatches."""
    return await _context_gate("/api/v1/context/gate")


async def _context_gate(path: str):
    try:
        return request_core("GET", path, timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context gate unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_context() -> dict:
    return {
        "account_id": None,
        "account_alias": None,
        "aws_profile": None,
        "region": None,
        "user_arn": None,
        "is_current": False,
    }

def _model_dump(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


async def get_current_system_context():
    return await _get_current_context("/api/v1/system/context")


async def list_system_contexts(current_user=Depends(get_current_user)):
    return await _list_contexts("/api/v1/system/contexts")


async def add_system_context(
    body: AddContextRequest,
    _user: Optional[dict] = Depends(get_current_user),
):
    return await _add_context("/api/v1/system/context", body)


async def switch_system_context(
    body: SwitchContextRequest,
    _user: Optional[dict] = Depends(get_current_user),
):
    return await _switch_context("/api/v1/system/context/switch", body)


async def remove_system_context(
    account_id: str,
    _user: Optional[dict] = Depends(get_current_user),
):
    return await _remove_context("/api/v1/system/context", account_id)


async def system_context_gate():
    return await _context_gate("/api/v1/system/context/gate")


# Tag Manager-compatible system aliases. Keep these on the same router so the
# BlueArch setup frontend can use the shared core account-context contract.
router.add_api_route("/system/context", get_current_system_context, methods=["GET"])
router.add_api_route("/system/contexts", list_system_contexts, methods=["GET"])
router.add_api_route("/system/context", add_system_context, methods=["POST"])
router.add_api_route("/system/context/switch", switch_system_context, methods=["POST"])
router.add_api_route("/system/context/{account_id}", remove_system_context, methods=["DELETE"])
router.add_api_route("/system/context/gate", system_context_gate, methods=["GET"])
