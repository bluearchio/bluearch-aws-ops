"""Custom alarm management API.

Lets users create alarms that track recommendations matching arbitrary
criteria, evaluate them on demand, and receive notifications when match counts
cross a threshold.
"""

import json
import logging
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import List, Optional
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.core_client import request_core
from web.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alarms", tags=["alarms"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NotificationTarget(BaseModel):
    type: str = Field(..., description="email | slack | sns")
    value: str = Field(..., description="email address, slack webhook URL, or SNS topic ARN")
    label: Optional[str] = None


class AlarmCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_type: str = Field("recommendation", description="recommendation")
    recommendation_types: List[str] = []
    resource_types: List[str] = []
    account_ids: List[str] = []
    regions: List[str] = []
    severity_filter: Optional[str] = None
    threshold: int = 1
    notification_targets: List[NotificationTarget] = []
    enabled: bool = True


class AlarmUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    recommendation_types: Optional[List[str]] = None
    resource_types: Optional[List[str]] = None
    account_ids: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    severity_filter: Optional[str] = None
    threshold: Optional[int] = None
    notification_targets: Optional[List[NotificationTarget]] = None
    enabled: Optional[bool] = None


class AlarmResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    trigger_type: str
    recommendation_types: List[str] = []
    resource_types: List[str] = []
    account_ids: List[str] = []
    regions: List[str] = []
    severity_filter: Optional[str] = None
    threshold: int
    notification_targets: List[NotificationTarget] = []
    enabled: bool
    last_evaluated_at: Optional[datetime] = None
    last_triggered_at: Optional[datetime] = None
    last_match_count: int = 0
    trigger_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None


class AlarmEventResponse(BaseModel):
    id: str
    alarm_id: str
    triggered_at: datetime
    match_count: int
    match_sample: Optional[list] = None
    notification_sent: bool = False
    notification_error: Optional[str] = None


class AlarmEvaluateResponse(BaseModel):
    alarm_id: str
    evaluated_at: datetime
    match_count: int
    threshold: int
    triggered: bool
    event_id: Optional[str] = None
    notification_status: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def _serialize_payload(payload: dict) -> AlarmResponse:
    raw_targets = _to_list(payload.get("notification_targets"))
    targets = []
    for t in raw_targets:
        if isinstance(t, dict) and t.get("type") and t.get("value"):
            targets.append(NotificationTarget(**t))
    return AlarmResponse(
        id=str(payload.get("id")),
        name=payload.get("name") or "",
        description=payload.get("description"),
        trigger_type=payload.get("trigger_type") or "recommendation",
        recommendation_types=_to_list(payload.get("recommendation_types")),
        resource_types=_to_list(payload.get("resource_types")),
        account_ids=_to_list(payload.get("account_ids")),
        regions=_to_list(payload.get("regions")),
        severity_filter=payload.get("severity_filter"),
        threshold=payload.get("threshold") or 1,
        notification_targets=targets,
        enabled=bool(payload.get("enabled", True)),
        last_evaluated_at=_parse_dt(payload.get("last_evaluated_at")),
        last_triggered_at=_parse_dt(payload.get("last_triggered_at")),
        last_match_count=payload.get("last_match_count") or 0,
        trigger_count=payload.get("trigger_count") or 0,
        created_at=_parse_dt(payload.get("created_at")),
        updated_at=_parse_dt(payload.get("updated_at")),
        created_by=payload.get("created_by"),
    )


def _event_payload_to_response(payload: dict) -> AlarmEventResponse:
    return AlarmEventResponse(
        id=str(payload.get("id")),
        alarm_id=str(payload.get("alarm_id")),
        triggered_at=_parse_dt(payload.get("triggered_at")) or datetime.now(timezone.utc),
        match_count=payload.get("match_count") or 0,
        match_sample=payload.get("match_sample") or [],
        notification_sent=bool(payload.get("notification_sent")),
        notification_error=payload.get("notification_error"),
    )


def _parse_dt(value):
    if isinstance(value, datetime) or value is None:
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _record_payload(record: dict) -> dict:
    return dict((record or {}).get("payload") or {})


def _core_storage_path(collection: str, record_key: str | None = None, query: str | None = None) -> str:
    path = f"/api/v1/storage/bluearch/{collection}"
    if record_key:
        path = f"{path}/{record_key}"
    if query:
        path = f"{path}?{query}"
    return path


def _core_list_payloads(collection: str, *, limit: int = 5000, filters: list[tuple[str, str]] | None = None, order_by: str | None = None, descending: bool = True) -> list[dict]:
    from urllib.parse import urlencode

    params: list[tuple[str, str | int | bool]] = [("limit", limit), ("descending", str(descending).lower())]
    if order_by:
        params.append(("order_by", order_by))
    for key, value in filters or []:
        params.append(("filter", f"{key}={value}"))
    records = request_core(
        "GET",
        _core_storage_path(collection, query=urlencode(params)),
        service_token=True,
        timeout=10.0,
    )
    return [_record_payload(record) for record in records]


def _core_get_payload(collection: str, record_key: str) -> dict:
    try:
        record = request_core(
            "GET",
            _core_storage_path(collection, record_key),
            service_token=True,
            timeout=10.0,
        )
    except Exception as exc:
        if "404" in str(exc):
            raise HTTPException(status_code=404, detail="Alarm not found") from exc
        raise
    return _record_payload(record)


def _core_create_payload(collection: str, payload: dict) -> dict:
    record = request_core(
        "POST",
        _core_storage_path(collection),
        service_token=True,
        json={"payload": payload},
        timeout=10.0,
    )
    return _record_payload(record)


def _core_update_payload(collection: str, record_key: str, payload: dict) -> dict:
    record = request_core(
        "PUT",
        _core_storage_path(collection, record_key),
        service_token=True,
        json={"payload": payload},
        timeout=10.0,
    )
    return _record_payload(record)


def _core_delete_payload(collection: str, record_key: str) -> None:
    request_core(
        "DELETE",
        _core_storage_path(collection, record_key),
        service_token=True,
        timeout=10.0,
    )


def _core_alarm_to_namespace(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=payload.get("id"),
        name=payload.get("name"),
        description=payload.get("description"),
        threshold=payload.get("threshold") or 1,
        notification_targets=payload.get("notification_targets") or [],
    )


def _core_count_matches(alarm: dict) -> tuple[int, list]:
    rec_types = _to_list(alarm.get("recommendation_types"))
    resource_types = set(_to_list(alarm.get("resource_types")))
    account_ids = _to_list(alarm.get("account_ids"))
    regions = _to_list(alarm.get("regions"))

    filters = []
    if len(rec_types) == 1:
        filters.append(("recommendation_type", rec_types[0]))
    if len(account_ids) == 1:
        filters.append(("account_id", account_ids[0]))
    if len(regions) == 1:
        filters.append(("region_name", regions[0]))

    records = _core_list_payloads("recommendations", filters=filters, order_by="last_updated")
    total = 0
    sample: list = []
    for rec in records:
        if rec_types and rec.get("recommendation_type") not in rec_types:
            continue
        if account_ids and rec.get("account_id") not in account_ids:
            continue
        if regions and rec.get("region_name") not in regions:
            continue
        if resource_types and not _core_resource_matches_type(rec.get("resource_id"), resource_types):
            continue
        total += 1
        if len(sample) < 20:
            sample.append(
                {
                    "kind": "recommendation",
                    "id": rec.get("id"),
                    "type": rec.get("recommendation_type"),
                    "resource_id": rec.get("resource_id"),
                    "account_id": rec.get("account_id"),
                    "region": rec.get("region_name"),
                }
            )
    return total, sample


def _core_resource_matches_type(resource_id: str | None, resource_types: set[str]) -> bool:
    if not resource_id:
        return False
    try:
        resource = request_core("GET", f"/api/v1/resources/{resource_id}", timeout=5.0)
    except Exception:
        return False
    return resource.get("service_name") in resource_types or resource.get("resource_type") in resource_types


def _core_alarm_options() -> dict:
    recs = _core_list_payloads("recommendations", order_by="last_updated")
    summary = request_core("GET", "/api/v1/resources/summary", timeout=5.0)
    return {
        "recommendation_types": sorted({r.get("recommendation_type") for r in recs if r.get("recommendation_type")}),
        "account_ids": sorted({row.get("account_id") for row in summary.get("by_account", []) if row.get("account_id")}),
        "regions": sorted({row.get("region") for row in summary.get("by_region", []) if row.get("region")}),
        "resource_types": sorted({row.get("service_name") for row in summary.get("by_service", []) if row.get("service_name")}),
        "severities": ["low", "medium", "high", "critical"],
        "notification_types": ["slack", "sns", "email"],
    }


def _send_notification(alarm, match_count: int, sample: list) -> tuple[bool, Optional[str]]:
    """Send notifications to all targets. Returns (all_ok, first_error)."""
    targets = _to_list(alarm.notification_targets)
    if not targets:
        return True, None

    payload_title = f"BlueArch alarm: {alarm.name}"
    payload_body = (
        f"Alarm '{alarm.name}' triggered with {match_count} matching "
        f"{'finding' if match_count == 1 else 'findings'} (threshold: {alarm.threshold})."
    )
    if alarm.description:
        payload_body += f"\n\n{alarm.description}"

    first_error: Optional[str] = None
    any_ok = False

    for target in targets:
        if not isinstance(target, dict):
            continue
        ttype = (target.get("type") or "").lower()
        value = target.get("value") or ""
        if not value:
            continue

        try:
            if ttype == "slack":
                _send_slack(value, payload_title, payload_body)
                any_ok = True
            elif ttype == "sns":
                _send_sns(value, payload_title, payload_body)
                any_ok = True
            elif ttype == "email":
                _send_email_via_sns(value, payload_title, payload_body)
                any_ok = True
            else:
                logger.warning("Unknown notification target type: %s", ttype)
        except Exception as e:
            logger.error("Notification failed for %s (%s): %s", ttype, value, e)
            if first_error is None:
                first_error = f"{ttype}: {e}"

    return any_ok and first_error is None, first_error


def _send_slack(webhook_url: str, title: str, body: str) -> None:
    payload = {"text": f"*{title}*\n{body}"}
    data = json.dumps(payload).encode("utf-8")
    req = Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Slack webhook returned {resp.status}")


def _send_sns(topic_arn: str, title: str, body: str) -> None:
    import boto3

    sns = boto3.client("sns")
    sns.publish(TopicArn=topic_arn, Subject=title[:100], Message=body)


def _send_email_via_sns(email: str, title: str, body: str) -> None:
    """Email delivery piggybacks on an ad-hoc SNS topic.

    Creates a transient topic per-email, subscribes the address, publishes,
    and leaves it in place. Users who want first-class email can subscribe
    their address to an SNS topic and configure that topic as an 'sns' target.
    """
    import boto3

    sns = boto3.client("sns")
    # Find-or-create a well-known topic for alarm emails
    topic_name = "bluearch-alarm-notifications"
    resp = sns.create_topic(Name=topic_name)  # idempotent
    topic_arn = resp["TopicArn"]

    # Ensure subscription exists
    existing = sns.list_subscriptions_by_topic(TopicArn=topic_arn).get("Subscriptions", [])
    has_sub = any(
        s.get("Protocol") == "email" and s.get("Endpoint") == email for s in existing
    )
    if not has_sub:
        sns.subscribe(TopicArn=topic_arn, Protocol="email", Endpoint=email)

    sns.publish(TopicArn=topic_arn, Subject=title[:100], Message=body)


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=List[AlarmResponse])
async def list_alarms(
    current_user=Depends(get_current_user),
):
    """List all custom alarms."""
    alarms = _core_list_payloads("alarms", order_by="created_at")
    result = [_serialize_payload(a) for a in alarms]


    return result


@router.post("", response_model=AlarmResponse)
async def create_alarm(
    body: AlarmCreate,
    user: Optional[dict] = Depends(get_current_user),
):
    """Create a new custom alarm."""
    if body.trigger_type != "recommendation":
        raise HTTPException(status_code=400, detail="trigger_type must be recommendation")

    if not body.recommendation_types:
        pass

    payload = {
        "name": body.name,
        "description": body.description,
        "trigger_type": body.trigger_type,
        "recommendation_types": body.recommendation_types,
        "resource_types": body.resource_types,
        "account_ids": body.account_ids,
        "regions": body.regions,
        "severity_filter": body.severity_filter,
        "threshold": max(1, body.threshold),
        "notification_targets": [_model_dump(t) for t in body.notification_targets],
        "enabled": body.enabled,
        "created_by": getattr(user, "email", None),
    }
    return _serialize_payload(_core_create_payload("alarms", payload))


@router.get("/{alarm_id}", response_model=AlarmResponse)
async def get_alarm(
    alarm_id: str,
    _user: Optional[dict] = Depends(get_current_user),
):
    return _serialize_payload(_core_get_payload("alarms", alarm_id))


@router.patch("/{alarm_id}", response_model=AlarmResponse)
async def update_alarm(
    alarm_id: str,
    body: AlarmUpdate,
    _user: Optional[dict] = Depends(get_current_user),
):
    alarm = _core_get_payload("alarms", alarm_id)

    data = body.model_dump(exclude_unset=True)
    if "notification_targets" in data and data["notification_targets"] is not None:
        data["notification_targets"] = [
            _model_dump(t) if isinstance(t, NotificationTarget) else t
            for t in data["notification_targets"]
        ]
    if "threshold" in data and data["threshold"] is not None:
        data["threshold"] = max(1, data["threshold"])
    if data.get("trigger_type") not in (None, "recommendation"):
        raise HTTPException(status_code=400, detail="trigger_type must be recommendation")
    data["trigger_type"] = "recommendation"

    alarm.update(data)
    return _serialize_payload(_core_update_payload("alarms", alarm_id, alarm))


@router.delete("/{alarm_id}")
async def delete_alarm(
    alarm_id: str,
    _user: Optional[dict] = Depends(get_current_user),
):
    alarm = _core_get_payload("alarms", alarm_id)
    _core_delete_payload("alarms", alarm_id)
    return {"success": True, "message": f"Alarm '{alarm.get('name')}' deleted"}


# ---------------------------------------------------------------------------
# Evaluation + events
# ---------------------------------------------------------------------------


@router.post("/{alarm_id}/evaluate", response_model=AlarmEvaluateResponse)
async def evaluate_alarm(
    alarm_id: str,
    _user: Optional[dict] = Depends(get_current_user),
):
    """Evaluate an alarm against current findings/recommendations.

    If match_count >= threshold, records an AlarmEvent and sends notifications.
    """
    alarm = _core_get_payload("alarms", alarm_id)

    match_count, sample = _core_count_matches(alarm)
    now = datetime.now(timezone.utc)

    alarm["last_evaluated_at"] = now.isoformat()
    alarm["last_match_count"] = match_count

    triggered = match_count >= (alarm.get("threshold") or 1)
    event_id = None
    notification_status = None

    if triggered and alarm.get("enabled", True):
        ok, err = _send_notification(_core_alarm_to_namespace(alarm), match_count, sample)
        event = _core_create_payload(
            "alarm-events",
            {
                "alarm_id": alarm.get("id"),
                "triggered_at": now.isoformat(),
                "match_count": match_count,
                "match_sample": sample,
                "notification_sent": ok,
                "notification_error": err,
            },
        )
        alarm["last_triggered_at"] = now.isoformat()
        alarm["trigger_count"] = (alarm.get("trigger_count") or 0) + 1
        event_id = event.get("id")
        notification_status = "sent" if ok else f"error: {err}" if err else "skipped (no targets)"

    _core_update_payload("alarms", alarm_id, alarm)
    return AlarmEvaluateResponse(
        alarm_id=alarm_id,
        evaluated_at=now,
        match_count=match_count,
        threshold=alarm.get("threshold") or 1,
        triggered=triggered,
        event_id=event_id,
        notification_status=notification_status,
    )


@router.post("/evaluate-all")
async def evaluate_all(
    _user: Optional[dict] = Depends(get_current_user),
):
    """Evaluate every enabled alarm. Called after a scan completes."""
    alarms = [alarm for alarm in _core_list_payloads("alarms", order_by="created_at") if alarm.get("enabled", True)]
    results = []
    now = datetime.now(timezone.utc)
    for alarm in alarms:
        match_count, sample = _core_count_matches(alarm)
        alarm["last_evaluated_at"] = now.isoformat()
        alarm["last_match_count"] = match_count
        triggered = match_count >= (alarm.get("threshold") or 1)
        event_id = None
        if triggered:
            ok, err = _send_notification(_core_alarm_to_namespace(alarm), match_count, sample)
            event = _core_create_payload(
                "alarm-events",
                {
                    "alarm_id": alarm.get("id"),
                    "triggered_at": now.isoformat(),
                    "match_count": match_count,
                    "match_sample": sample,
                    "notification_sent": ok,
                    "notification_error": err,
                },
            )
            alarm["last_triggered_at"] = now.isoformat()
            alarm["trigger_count"] = (alarm.get("trigger_count") or 0) + 1
            event_id = event.get("id")
        if alarm.get("id"):
            _core_update_payload("alarms", alarm["id"], alarm)
        results.append(
            {
                "alarm_id": alarm.get("id"),
                "name": alarm.get("name"),
                "match_count": match_count,
                "triggered": triggered,
                "event_id": event_id,
            }
        )
    return {"evaluated": len(alarms), "results": results}


@router.get("/{alarm_id}/events", response_model=List[AlarmEventResponse])
async def list_alarm_events(
    alarm_id: str,
    limit: int = 50,
    _user: Optional[dict] = Depends(get_current_user),
):
    """List recent firing events for an alarm."""
    _core_get_payload("alarms", alarm_id)
    events = _core_list_payloads(
        "alarm-events",
        limit=min(limit, 200),
        filters=[("alarm_id", alarm_id)],
        order_by="triggered_at",
    )
    return [_event_payload_to_response(event) for event in events]


@router.post("/{alarm_id}/test")
async def test_alarm_notification(
    alarm_id: str,
    _user: Optional[dict] = Depends(get_current_user),
):
    """Send a test notification to all configured targets."""
    alarm = _core_get_payload("alarms", alarm_id)

    ok, err = _send_notification(
        _core_alarm_to_namespace(alarm),
        match_count=0,
        sample=[{"kind": "test", "note": "This is a test notification from BlueArch."}],
    )
    return {"success": ok, "error": err}


# ---------------------------------------------------------------------------
# Metadata - available recommendation types
# ---------------------------------------------------------------------------


@router.get("/meta/options")
async def get_alarm_options(
    _user: Optional[dict] = Depends(get_current_user),
):
    """Return the options the alarm creation form needs."""
    return _core_alarm_options()


def _model_dump(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
