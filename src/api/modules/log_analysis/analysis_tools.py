"""Tools exposed to the Bedrock model during root-cause analysis.

Each tool is a small, read-only AWS call that grounds the model's diagnosis
in real data (untruncated log lines, Lambda configuration, CloudWatch
metrics, collected resource metadata) instead of generic advice.

The tool set is intentionally narrow: Lambda-centric for now, because that
covers the bulk of AWS log errors surfaced by our regex filter. Additional
tools (RDS describe, ECS task describe, etc.) can be added without
changing the call site.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import boto3
from utils.core_client import request_core

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context + registry
# ---------------------------------------------------------------------------

@dataclass
class AnalysisContext:
    """Everything a tool implementation may need to answer a call."""

    finding: Any
    region: str
    session: Optional[boto3.Session] = None

    def client(self, service: str, region: Optional[str] = None):
        sess = self.session or boto3.Session(region_name=self.region)
        return sess.client(service, region_name=region or self.region)


ToolImpl = Callable[["AnalysisContext", Dict[str, Any]], Dict[str, Any]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    impl: ToolImpl

    def spec(self) -> Dict[str, Any]:
        """Bedrock Converse tool spec shape."""
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {"json": self.input_schema},
            }
        }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_DEFAULT_LOG_FETCH = 50
_MAX_LOG_FETCH = 200
_MAX_LINE_CHARS = 4000  # trim monster lines so one event doesn't blow the context


def _fetch_log_events(ctx: AnalysisContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """FilterLogEvents scoped to the finding's log group."""
    limit = min(int(args.get("limit") or _DEFAULT_LOG_FETCH), _MAX_LOG_FETCH)
    filter_pattern = args.get("filter_pattern")
    lookback_hours = args.get("lookback_hours")

    finding = ctx.finding
    if lookback_hours:
        end_ts = finding.last_seen or datetime.now(timezone.utc)
        start_ts = end_ts - timedelta(hours=float(lookback_hours))
    else:
        start_ts = finding.first_seen or (datetime.now(timezone.utc) - timedelta(hours=24))
        end_ts = finding.last_seen or datetime.now(timezone.utc)

    params: Dict[str, Any] = {
        "logGroupName": finding.log_group_name,
        "startTime": int(start_ts.timestamp() * 1000),
        "endTime": int(end_ts.timestamp() * 1000),
        "limit": limit,
    }
    if filter_pattern:
        params["filterPattern"] = filter_pattern

    try:
        resp = ctx.client("logs").filter_log_events(**params)
    except Exception as exc:
        return {"error": f"filter_log_events failed: {exc}"}

    events = []
    for e in resp.get("events", []):
        msg = (e.get("message") or "").rstrip()
        if len(msg) > _MAX_LINE_CHARS:
            msg = msg[:_MAX_LINE_CHARS] + "…[truncated]"
        events.append({
            "timestamp": e.get("timestamp"),
            "log_stream": e.get("logStreamName"),
            "message": msg,
        })
    return {
        "log_group": finding.log_group_name,
        "start_time": start_ts.isoformat(),
        "end_time": end_ts.isoformat(),
        "event_count": len(events),
        "events": events,
    }


def _describe_lambda(ctx: AnalysisContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """GetFunction for a Lambda. Function name defaults to the one parsed
    from the finding's log group (``/aws/lambda/<name>``) so the model
    doesn't have to pass it explicitly."""
    name = args.get("function_name")
    if not name:
        log_group = ctx.finding.log_group_name or ""
        if log_group.startswith("/aws/lambda/"):
            name = log_group[len("/aws/lambda/"):]
    if not name:
        return {"error": "function_name not provided and log group is not a Lambda log group"}

    region = args.get("region") or ctx.region
    try:
        resp = ctx.client("lambda", region=region).get_function(FunctionName=name)
    except Exception as exc:
        return {"error": f"get_function failed: {exc}"}

    cfg = resp.get("Configuration", {}) or {}
    env = (cfg.get("Environment") or {}).get("Variables") or {}
    # Redact anything that smells like a secret
    redacted_env = {k: ("***" if _looks_secret(k) else v) for k, v in env.items()}
    return {
        "function_name": cfg.get("FunctionName"),
        "runtime": cfg.get("Runtime"),
        "handler": cfg.get("Handler"),
        "memory_mb": cfg.get("MemorySize"),
        "timeout_sec": cfg.get("Timeout"),
        "architectures": cfg.get("Architectures"),
        "last_modified": cfg.get("LastModified"),
        "code_size_bytes": cfg.get("CodeSize"),
        "state": cfg.get("State"),
        "state_reason": cfg.get("StateReason"),
        "state_reason_code": cfg.get("StateReasonCode"),
        "dead_letter_queue": (cfg.get("DeadLetterConfig") or {}).get("TargetArn"),
        "vpc_config": cfg.get("VpcConfig"),
        "layers": [L.get("Arn") for L in cfg.get("Layers") or []],
        "tracing": (cfg.get("TracingConfig") or {}).get("Mode"),
        "environment_keys": list(env.keys()),
        "environment_sample": {k: v for k, v in list(redacted_env.items())[:12]},
    }


_SECRET_TOKENS = ("password", "secret", "token", "api_key", "apikey", "private", "auth", "credential")


def _looks_secret(key: str) -> bool:
    k = key.lower()
    return any(tok in k for tok in _SECRET_TOKENS)


_LAMBDA_METRIC_DEFAULTS = {
    "Invocations": "Sum",
    "Errors": "Sum",
    "Throttles": "Sum",
    "Duration": "Average",
    "ConcurrentExecutions": "Maximum",
    "IteratorAge": "Maximum",
}


def _get_cloudwatch_metric(ctx: AnalysisContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch a CloudWatch metric's last ``lookback_hours`` (default 24h),
    with sensible defaults for Lambda metrics so the model can just ask for
    ``Errors`` without knowing the namespace/dimensions."""
    namespace = args.get("namespace") or "AWS/Lambda"
    metric_name = args.get("metric_name")
    if not metric_name:
        return {"error": "metric_name is required"}

    dims_in = args.get("dimensions") or {}
    # Default dimension: FunctionName parsed from the log group
    if not dims_in and namespace == "AWS/Lambda":
        log_group = ctx.finding.log_group_name or ""
        if log_group.startswith("/aws/lambda/"):
            dims_in = {"FunctionName": log_group[len("/aws/lambda/"):]}

    dimensions = [{"Name": k, "Value": str(v)} for k, v in (dims_in or {}).items()]
    stat = args.get("statistic") or _LAMBDA_METRIC_DEFAULTS.get(metric_name, "Average")
    lookback_hours = float(args.get("lookback_hours") or 24)
    period = int(args.get("period_seconds") or 3600)

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    region = args.get("region") or ctx.region

    try:
        resp = ctx.client("cloudwatch", region=region).get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start,
            EndTime=end,
            Period=period,
            Statistics=[stat],
        )
    except Exception as exc:
        return {"error": f"get_metric_statistics failed: {exc}"}

    datapoints = sorted(resp.get("Datapoints", []) or [], key=lambda d: d.get("Timestamp"))
    values = [d.get(stat) for d in datapoints if d.get(stat) is not None]
    return {
        "namespace": namespace,
        "metric_name": metric_name,
        "dimensions": dims_in,
        "statistic": stat,
        "lookback_hours": lookback_hours,
        "datapoints": [
            {"timestamp": d.get("Timestamp").isoformat() if d.get("Timestamp") else None, "value": d.get(stat)}
            for d in datapoints
        ],
        "total": float(sum(values)) if stat == "Sum" and values else None,
        "max": float(max(values)) if values else None,
        "avg": round(sum(values) / len(values), 3) if values else None,
    }


def _get_resource_detail(ctx: AnalysisContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """Look up the linked Resource row in the shared DB. Useful for the
    model to understand what the log-producing resource actually is."""
    rid = args.get("resource_id") or ctx.finding.resource_id
    if not rid:
        return {"error": "No resource_id (finding is unlinked)."}
    try:
        record = request_core(
            "GET",
            f"/api/v1/storage/core/resources/{rid}",
            service_token=True,
            timeout=10.0,
        )
    except Exception as exc:
        return {"error": f"Resource {rid} not found: {exc}"}
    payload = record.get("payload", record)
    if not payload:
        return {"error": f"Resource {rid} not found"}
    return {
        "id": payload.get("id"),
        "resource_arn": payload.get("resource_arn"),
        "resource_type": payload.get("resource_type"),
        "service_name": payload.get("service_name"),
        "region": payload.get("region"),
        "account_id": payload.get("account_id"),
        "resource_id_aws": payload.get("resource_id"),
        "current_tags": payload.get("current_tags") or {},
        "metadata": payload.get("metadata_json") or payload.get("metadata") or {},
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ANALYSIS_TOOLS: List[Tool] = [
    Tool(
        name="fetch_log_events",
        description=(
            "Fetch recent CloudWatch log events from the finding's log group. "
            "Use this when you need more context than the sample already in the prompt, "
            "or to search for specific error tokens. Returns up to 200 events."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "filter_pattern": {
                    "type": "string",
                    "description": "CloudWatch filter pattern (e.g. \"ERROR\" or \"KeyError\"). Omit to fetch all events in the window.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max events (default 50, cap 200).",
                },
                "lookback_hours": {
                    "type": "number",
                    "description": "Hours back from the finding's last_seen. Defaults to the finding's first_seen..last_seen window.",
                },
            },
        },
        impl=_fetch_log_events,
    ),
    Tool(
        name="describe_lambda_function",
        description=(
            "GetFunction for a Lambda. Function name defaults to the one parsed from "
            "the finding's log group. Returns runtime, memory, timeout, layers, VPC "
            "config, DLQ, tracing, env var *keys* (values are redacted if they smell "
            "like secrets). Use this whenever the log group is /aws/lambda/*."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "region": {"type": "string"},
            },
        },
        impl=_describe_lambda,
    ),
    Tool(
        name="get_cloudwatch_metric",
        description=(
            "Pull a CloudWatch metric over a lookback window. Defaults to AWS/Lambda "
            "with dimensions auto-populated from the log group. Common metrics: "
            "Invocations, Errors, Throttles, Duration, ConcurrentExecutions, "
            "IteratorAge. Use this to quantify the impact (how many errors? what "
            "percentage of invocations?) and the blast radius."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "Default: AWS/Lambda"},
                "metric_name": {"type": "string"},
                "dimensions": {"type": "object", "additionalProperties": {"type": "string"}},
                "statistic": {
                    "type": "string",
                    "enum": ["Sum", "Average", "Maximum", "Minimum", "SampleCount"],
                },
                "lookback_hours": {"type": "number"},
                "period_seconds": {"type": "integer"},
                "region": {"type": "string"},
            },
            "required": ["metric_name"],
        },
        impl=_get_cloudwatch_metric,
    ),
    Tool(
        name="get_resource_detail",
        description=(
            "Look up the linked Resource row (from the shared scan DB). Returns "
            "arn, type, region, current tags, and collector-captured metadata. "
            "Only works when the finding is resource-linked."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "resource_id": {"type": "string"},
            },
        },
        impl=_get_resource_detail,
    ),
]


def tool_specs() -> List[Dict[str, Any]]:
    return [t.spec() for t in ANALYSIS_TOOLS]


def dispatch_tool(name: str, input_args: Dict[str, Any], ctx: AnalysisContext) -> Dict[str, Any]:
    """Execute a tool by name. Returns a JSON-serializable dict; errors are
    encoded as ``{"error": "..."}`` so the model can react rather than the
    whole turn crashing."""
    for t in ANALYSIS_TOOLS:
        if t.name == name:
            try:
                return t.impl(ctx, input_args or {})
            except Exception as exc:
                logger.warning("Tool %s raised: %s", name, exc)
                return {"error": f"tool {name} raised {type(exc).__name__}: {exc}"}
    return {"error": f"unknown tool {name!r}"}


def tool_result_json(result: Dict[str, Any]) -> str:
    """Serialize a tool result for Bedrock. Kept short by truncating log
    events if the JSON exceeds a safety cap."""
    s = json.dumps(result, default=str)
    cap = 60_000  # characters, well under any Bedrock content-block limit
    if len(s) > cap:
        # Drop oldest events first if present
        if isinstance(result.get("events"), list):
            trimmed = dict(result)
            trimmed["events"] = result["events"][: len(result["events"]) // 2]
            trimmed["_truncated"] = True
            return tool_result_json(trimmed)
        return s[:cap] + "…[truncated]"
    return s
