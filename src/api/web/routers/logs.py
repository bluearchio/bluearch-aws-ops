"""Log Analysis API endpoints — /api/v1/logs/*.

Log scanning is now part of the unified resource scan (see the `logs`
collector in modules/collection/). This router only exposes read-only
listing endpoints plus on-demand Bedrock analysis.
"""

import asyncio
import json
import queue
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from utils.core_client import CoreRuntimeError, request_core
from web.core_storage import get_storage_payload, list_storage_payloads, update_storage_payload
from web.schemas.logs import (
    AnalyzeRequest,
    AnalyzeResponse,
    ListFindingsResponse,
    LogFindingResponse,
    ScanSummary,
)

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


# ---------------------------------------------------------------------------
# Scans (read-only — scans are triggered through /api/v1/scans now)
# ---------------------------------------------------------------------------

@router.get("/scans", response_model=list[ScanSummary])
async def list_scans(
    limit: int = Query(20, ge=1, le=200),
):
    """List recent log scans (populated by `bluearch-aws-ops scan`)."""
    rows = list_storage_payloads(
        "bluearch",
        "log-scans",
        limit=limit,
        order_by="started_at",
        descending=True,
    )
    return [ScanSummary(**row) for row in rows]


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# A `bluearch scan` runs the LogsCollector once per region, so a single scan
# invocation emits ~N LogScan rows (one per region). When the client asks for
# "the latest findings" without pinning a specific scan_id, we treat scans
# that started within this window of the latest one as a single batch.
_SCAN_BATCH_WINDOW = timedelta(minutes=10)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _dt_sort(value: Any) -> float:
    parsed = _parse_dt(value)
    return parsed.timestamp() if parsed else 0.0


def _latest_batch_scan_ids() -> List[str]:
    """Return the scan ids that belong to the most recent scan batch.

    "Batch" = all LogScans for the latest account whose `started_at` falls
    within ``_SCAN_BATCH_WINDOW`` of the latest scan's start. Prevents the
    UI from showing only one region when a single `bluearch scan` wrote 18+
    region-scoped LogScan rows.
    """
    scans = list_storage_payloads(
        "bluearch",
        "log-scans",
        limit=500,
        order_by="started_at",
        descending=True,
    )
    if not scans:
        return []
    latest = scans[0]
    latest_started_at = _parse_dt(latest.get("started_at"))
    if latest_started_at is None:
        return []
    account_id = latest.get("account_id")
    window_start = latest_started_at - _SCAN_BATCH_WINDOW
    return [
        row["id"]
        for row in scans
        if row.get("id")
        and row.get("account_id") == account_id
        and (started_at := _parse_dt(row.get("started_at"))) is not None
        and started_at >= window_start
    ]


@router.get("/findings", response_model=ListFindingsResponse)
async def list_findings(
    scan_id: Optional[str] = Query(None),
    link_status: Optional[str] = Query(None, pattern="^(linked|unlinked)$"),
    severity: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    resource_id: Optional[str] = Query(None),
    status: str = Query("open"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """List log analysis findings with filters."""

    batch_ids: set[str] | None = None
    if scan_id:
        batch_ids = {scan_id}
    else:
        latest_ids = _latest_batch_scan_ids()
        batch_ids = set(latest_ids) if latest_ids else None

    rows = list_storage_payloads(
        "bluearch",
        "log-findings",
        limit=10000,
        order_by="detected_at",
        descending=True,
    )

    def _matches(row: dict) -> bool:
        if batch_ids is not None and row.get("scan_id") not in batch_ids:
            return False
        if link_status and row.get("link_status") != link_status:
            return False
        if severity and row.get("severity") != severity:
            return False
        if resource_id and row.get("resource_id") != resource_id:
            return False
        if status and row.get("status") != status:
            return False
        return True

    filtered = [row for row in rows if _matches(row)]
    filtered.sort(
        key=lambda row: (
            _SEVERITY_RANK.get(row.get("severity") or "", 9),
            -(row.get("occurrence_count") or 0),
            -_dt_sort(row.get("detected_at")),
        )
    )
    total = len(filtered)
    page_rows = filtered[(page - 1) * page_size: page * page_size]
    items = [LogFindingResponse(**row) for row in page_rows]

    return ListFindingsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/findings/{finding_id}", response_model=LogFindingResponse)
async def get_finding(finding_id: str):
    """Fetch one finding by id."""
    try:
        row = get_storage_payload("bluearch", "log-findings", finding_id)
    except CoreRuntimeError as exc:
        if "404" in str(exc):
            raise HTTPException(status_code=404, detail="Finding not found") from exc
        raise
    if not row:
        raise HTTPException(status_code=404, detail="Finding not found")
    return LogFindingResponse(**row)


# ---------------------------------------------------------------------------
# AI analysis
# ---------------------------------------------------------------------------

@router.post("/findings/{finding_id}/analyze", response_model=AnalyzeResponse)
async def analyze_finding(
    finding_id: str,
    body: AnalyzeRequest,
):
    """Trigger on-demand Bedrock root-cause analysis for a finding.

    Non-streaming — useful for scripts / the CLI. The web UI prefers the
    streaming variant below so the user sees tool calls in real time.
    """

    row = _get_finding_payload(finding_id)
    service, finding, resource = _analysis_context(row)
    analysis = await asyncio.to_thread(
        _run_analysis,
        service,
        finding,
        resource,
        body.model,
    )
    analyzed_at = datetime.now(timezone.utc)
    row["ai_analysis"] = analysis
    row["ai_analyzed_at"] = analyzed_at
    update_storage_payload("bluearch", "log-findings", finding_id, row)
    return AnalyzeResponse(
        finding_id=finding_id,
        analysis=analysis,
        model=body.model,
        analyzed_at=analyzed_at,
    )


@router.post("/findings/{finding_id}/analyze/stream")
async def analyze_finding_stream(
    finding_id: str,
    body: AnalyzeRequest,
):
    """Streaming variant of the analyzer.

    Emits Server-Sent Events as the Bedrock model produces text and as each
    tool invocation / result happens. Final ``{type:"done", analysis:"..."}``
    event is emitted after the model finishes and the row is persisted.
    """

    # Resolve everything the streamer needs inside a short DB session so
    # the thread below doesn't hold a connection the whole time.
    from modules.log_analysis.analysis_tools import (
        AnalysisContext,
        dispatch_tool,
        tool_result_json,
        tool_specs,
    )
    from modules.ai.bedrock_client import converse_stream_with_tools
    from modules.log_analysis.service import LogAnalysisService

    row = _get_finding_payload(finding_id)
    service, finding, resource = _analysis_context(row)
    samples = service._fetch_samples(finding)  # noqa: SLF001
    prompt = service._build_prompt(finding, resource, samples)  # noqa: SLF001

    ctx = AnalysisContext(finding=finding, region=service.region, session=service._session)

    def _dispatch(name: str, args: dict) -> str:
        return tool_result_json(dispatch_tool(name, args or {}, ctx))

    q: "queue.Queue" = queue.Queue()
    _DONE = object()

    def _run() -> None:
        try:
            for event in converse_stream_with_tools(
                prompt=prompt,
                tools=tool_specs(),
                tool_dispatcher=_dispatch,
                model_alias=body.model,
                region=service.region,
                system_prompt=(
                    "You are an AWS infrastructure SRE. Produce a grounded, "
                    "specific root-cause report for a CloudWatch log error. "
                    "You MUST use the tools to fetch real data before "
                    "concluding — never rely on generic guesses. Cite the "
                    "concrete values you observed. Format the report as "
                    "clean GitHub-flavored markdown with headings and lists."
                ),
            ):
                q.put(event)
        except Exception as exc:
            q.put({"type": "error", "message": str(exc)})
        finally:
            q.put(_DONE)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    async def _sse():
        final_analysis: Optional[str] = None
        while True:
            event = await asyncio.to_thread(q.get)
            if event is _DONE:
                break
            if event.get("type") == "done":
                final_analysis = event.get("analysis") or ""
            yield f"data: {json.dumps(event, default=str)}\n\n"

        # Persist after the stream completes, in a tiny session
        if final_analysis is not None:
            row["ai_analysis"] = final_analysis
            row["ai_analyzed_at"] = datetime.now(timezone.utc)
            update_storage_payload("bluearch", "log-findings", finding_id, row)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _get_finding_payload(finding_id: str) -> dict[str, Any]:
    try:
        row = get_storage_payload("bluearch", "log-findings", finding_id)
    except CoreRuntimeError as exc:
        if "404" in str(exc):
            raise HTTPException(status_code=404, detail="Finding not found") from exc
        raise
    if not row:
        raise HTTPException(status_code=404, detail="Finding not found")
    return row


def _namespace_from_payload(payload: dict[str, Any]) -> SimpleNamespace:
    values = dict(payload)
    for field in ("first_seen", "last_seen", "detected_at", "ai_analyzed_at"):
        values[field] = _parse_dt(values.get(field))
    return SimpleNamespace(**values)


def _get_resource(resource_id: str | None) -> SimpleNamespace | None:
    if not resource_id:
        return None
    try:
        payload = request_core("GET", f"/api/v1/resources/{resource_id}")
    except CoreRuntimeError:
        return None
    return SimpleNamespace(**payload) if isinstance(payload, dict) else None


def _analysis_context(row: dict[str, Any]):
    from modules.log_analysis.service import LogAnalysisService

    service = LogAnalysisService(region=None)
    finding = _namespace_from_payload(row)
    resource = _get_resource(row.get("resource_id"))
    return service, finding, resource


def _run_analysis(service, finding, resource, model: str) -> str:
    from modules.ai.bedrock_client import converse_with_tools
    from modules.log_analysis.analysis_tools import (
        AnalysisContext,
        dispatch_tool,
        tool_result_json,
        tool_specs,
    )

    samples = service._fetch_samples(finding)  # noqa: SLF001
    prompt = service._build_prompt(finding, resource, samples)  # noqa: SLF001
    ctx = AnalysisContext(finding=finding, region=service.region, session=service._session)

    def _dispatch(name, args):
        return tool_result_json(dispatch_tool(name, args or {}, ctx))

    return converse_with_tools(
        prompt=prompt,
        tools=tool_specs(),
        tool_dispatcher=_dispatch,
        model_alias=model,
        region=service.region,
        system_prompt=(
            "You are an AWS infrastructure SRE. Your job is to produce a "
            "grounded, specific root-cause report for a CloudWatch log error. "
            "You MUST use the tools to fetch real data before concluding. "
            "Cite concrete values you observed and include actionable fixes."
        ),
    )
