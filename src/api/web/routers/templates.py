"""CloudFormation template viewing endpoints backed by bluearch-core."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from utils.core_client import request_core, request_core_response
from web.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/system/templates", tags=["templates"])


class TemplateMetadataResponse(BaseModel):
    name: str
    description: str
    public_url: str = ""
    version: str = ""


class TemplateDetailResponse(TemplateMetadataResponse):
    content: str


def _core_template_request(path: str):
    try:
        return request_core("GET", path, timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core template proxy failed: {exc}") from exc


@router.get("", response_model=List[TemplateMetadataResponse])
async def list_templates(current_user=Depends(get_current_user)):
    """List available CloudFormation templates."""
    result = _core_template_request("/api/v1/system/templates")

    return result


@router.get("/component-map")
async def get_component_template_map(
    _user: Optional[dict] = Depends(get_current_user),
):
    """Return mapping of infrastructure component keys to template names."""
    return _core_template_request("/api/v1/system/templates/component-map")


@router.get("/{name}", response_model=TemplateDetailResponse)
async def get_template(name: str, _user: Optional[dict] = Depends(get_current_user)):
    """Return template YAML content."""
    return _core_template_request(f"/api/v1/system/templates/{name}")


@router.get("/{name}/raw")
async def get_template_raw(name: str, _user: Optional[dict] = Depends(get_current_user)):
    """Return raw YAML content for viewing."""
    try:
        response = request_core_response(
            "GET",
            f"/api/v1/system/templates/{name}/raw",
            timeout=5.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core template proxy failed: {exc}") from exc
    return PlainTextResponse(response.text, media_type="text/plain")
