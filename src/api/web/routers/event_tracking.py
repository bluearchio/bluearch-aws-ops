"""Event tracking endpoints proxied to bluearch-core."""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.event_hooks import track_event
from utils.core_client import request_core
from web.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/event-tracking", tags=["event-tracking"])


class EventTrackingInstanceStatus(BaseModel):
    account_id: str
    region: str
    status: str
    queue_url: str = ""
    queue_arn: str = ""
    stack_id: str = ""
    last_polled_at: Optional[str] = None
    last_event_at: Optional[str] = None
    messages_processed: int = 0
    events_today: int = 0
    error_message: Optional[str] = None


class EventTrackingStatusResponse(BaseModel):
    stackset_exists: bool = False
    stackset_status: str = ""
    instances: List[EventTrackingInstanceStatus] = []
    service_running: bool = False
    service_paused: bool = False
    total_queues: int = 0
    active_queues: int = 0


class EventTrackingDeployRequest(BaseModel):
    targets: Dict[str, List[str]] = {}


class EventTrackingRemoveRequest(BaseModel):
    targets: Dict[str, List[str]] = {}


class EventTrackingSyncAction(BaseModel):
    action: str


class EventTrackingPollRequest(BaseModel):
    max_messages: int = 10
    wait_time_seconds: int = 0
    visibility_timeout: int = 60


class JobSubmittedResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    message: str


def _core_get(path: str):
    return request_core("GET", path, timeout=10.0)


def _core_post(path: str, payload: dict | None = None):
    return request_core("POST", path, service_token=True, json=payload or {}, timeout=30.0)


def _submitted(row: dict, job_type: str, message: str) -> JobSubmittedResponse:
    return JobSubmittedResponse(
        job_id=row.get("id") or row.get("job_id") or "",
        job_type=row.get("job_type") or job_type,
        status=row.get("status") or "pending",
        message=row.get("message") or message,
    )


@router.get("/status", response_model=EventTrackingStatusResponse)
async def get_event_tracking_status(current_user=Depends(get_current_user)):
    """Get event tracking status from bluearch-core."""
    try:
        result = _core_get("/api/v1/event-tracking/status")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking unavailable: {exc}") from exc
    try:
        track_event(
            "web.event_tracking.status",
            properties={
                "user_sub": getattr(current_user, "sub", None),
                "instances": len(result.get("instances", [])),
                "source": "bluearch-core",
            },
        )
    except Exception:
        pass
    return result


@router.post("/deploy", response_model=JobSubmittedResponse)
async def deploy_event_tracking(body: EventTrackingDeployRequest, _user=Depends(get_current_user)):
    """Deploy or sync event tracking through bluearch-core."""
    try:
        return _submitted(_core_post("/api/v1/event-tracking/deploy", body.model_dump()), "event_tracking_deploy", "Event tracking deployment started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking deploy unavailable: {exc}") from exc


@router.post("/remove", response_model=JobSubmittedResponse)
async def remove_event_tracking(body: EventTrackingRemoveRequest, _user=Depends(get_current_user)):
    """Remove selected event tracking targets through bluearch-core."""
    try:
        return _submitted(_core_post("/api/v1/event-tracking/remove", body.model_dump()), "event_tracking_remove", "Event tracking removal started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking remove unavailable: {exc}") from exc


@router.post("/remove-all", response_model=JobSubmittedResponse)
async def remove_all_event_tracking(_user=Depends(get_current_user)):
    """Remove all event tracking targets through bluearch-core."""
    try:
        return _submitted(_core_post("/api/v1/event-tracking/remove-all"), "event_tracking_remove_all", "Event tracking removal started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking remove unavailable: {exc}") from exc


@router.post("/service")
async def service_action(body: EventTrackingSyncAction, _user=Depends(get_current_user)):
    """Control the core event tracking service."""
    try:
        return _core_post("/api/v1/event-tracking/service", body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking service unavailable: {exc}") from exc


@router.post("/poll")
async def poll_event_tracking(body: EventTrackingPollRequest, _user=Depends(get_current_user)):
    """Poll event queues through bluearch-core."""
    try:
        return _core_post("/api/v1/event-tracking/poll", body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking poll unavailable: {exc}") from exc
