"""Log Analysis orchestrator — discover log groups, run Insights queries,
normalize + group findings, link to resources, persist, and run on-demand
Bedrock root-cause analysis."""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from modules.ai.bedrock_client import converse_with_tools
from modules.log_analysis.analysis_tools import (
    AnalysisContext,
    dispatch_tool,
    tool_result_json,
    tool_specs,
)
from modules.log_analysis.queries import INSIGHTS_QUERY, group_findings
from modules.log_analysis.severity import classify_severity
from utils.core_client import request_core
from utils.local_cache import TTL_LOG_SAMPLES, cache_manager

logger = logging.getLogger(__name__)


# Tunables — conservative defaults within AWS limits.
_MAX_CONCURRENT_QUERIES = 10       # AWS limit 30; leave headroom
_QUERY_POLL_INTERVAL = 1.0         # seconds
_QUERY_POLL_MAX_WAIT = 120.0       # seconds per query
_SAMPLE_FETCH_LIMIT = 50           # lines per finding for AI analysis
_CORE_RESOURCE_PAGE_SIZE = 1000
_CORE_RESOURCE_SCAN_LIMIT = 10000

_NAMING_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"^/aws/lambda/(.+)$"), "lambda", "AWS::Lambda::Function"),
    (re.compile(r"^/aws/rds/instance/([^/]+)/.*$"), "rds", "AWS::RDS::DBInstance"),
    (re.compile(r"^/aws/rds/cluster/([^/]+)/.*$"), "rds", "AWS::RDS::DBCluster"),
    (re.compile(r"^/aws/ecs/containerinsights/[^/]+/([^/]+)/.*$"), "ecs", "AWS::ECS::Service"),
    (re.compile(r"^/aws/eks/([^/]+)/.*$"), "eks", "AWS::EKS::Cluster"),
    (re.compile(r"^/aws/elasticache/([^/]+).*$"), "elasticache", "AWS::ElastiCache::CacheCluster"),
    (re.compile(r"^/aws/apigateway/([^/]+).*$"), "apigateway", "AWS::ApiGateway::RestApi"),
]


class LogAnalysisService:
    """End-to-end log analysis service.

    Typical usage:
        service = LogAnalysisService(region="us-east-1")
        scan = service.run_scan(time_window_hours=24)
        analysis_text = service.analyze_finding(finding_id)
    """

    def __init__(
        self,
        region: Optional[str] = None,
        session: Optional[boto3.Session] = None,
    ):
        self.region = region or (session.region_name if session else None) or "us-east-1"
        self._session = session or boto3.Session(region_name=self.region)
        self._logs = self._session.client("logs", region_name=self.region)
        self._sts = self._session.client("sts", region_name=self.region)

    # =======================================================================
    # Scan orchestration
    # =======================================================================

    def run_scan(
        self,
        time_window_hours: int = 24,
        log_group_prefix: Optional[str] = None,
        max_groups: int = 500,
        min_severity: str = "low",
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict:
        """Execute a full scan end-to-end.

        Args:
            time_window_hours: Lookback window (default 24h).
            log_group_prefix: Optional prefix filter (e.g. "/aws/lambda/").
            max_groups: Safety cap on number of groups scanned.
            min_severity: Filter findings below this level out of the summary.
            progress_callback: Optional fn(done, total, current_group).

        Returns:
            dict with scan_id, findings_count, log_groups_scanned.
        """
        account_id = self._get_account_id()
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=time_window_hours)

        scan_id = self._create_scan_record(
            account_id=account_id,
            time_window_hours=time_window_hours,
        )

        try:
            log_groups = self.discover_log_groups(
                prefix=log_group_prefix,
                max_groups=max_groups,
            )
            logger.info(
                "Scanning %d log groups (region=%s, window=%dh)",
                len(log_groups), self.region, time_window_hours,
            )

            findings, permission_error_details = self._run_queries(
                log_groups=log_groups,
                start_time=start_time,
                end_time=end_time,
                progress_callback=progress_callback,
            )

            severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            min_rank = severity_rank.get(min_severity, 3)
            filtered = [f for f in findings if severity_rank.get(f["severity"], 3) <= min_rank]

            self._persist_findings(scan_id=scan_id, findings=filtered)
            self._complete_scan_record(
                scan_id=scan_id,
                log_groups_scanned=len(log_groups),
                findings_count=len(filtered),
                status="completed",
            )
            return {
                "scan_id": scan_id,
                "log_groups_scanned": len(log_groups),
                "findings_count": len(filtered),
                "permission_errors": len(permission_error_details),
                "permission_error_details": permission_error_details,
            }
        except Exception as exc:
            logger.exception("Log scan failed")
            self._complete_scan_record(
                scan_id=scan_id,
                log_groups_scanned=0,
                findings_count=0,
                status="failed",
                error_message=str(exc),
            )
            raise

    # -- Discovery -----------------------------------------------------------

    def discover_log_groups(
        self,
        prefix: Optional[str] = None,
        max_groups: int = 500,
    ) -> List[Dict]:
        """List non-empty log groups in the current region.

        Skips groups with `storedBytes == 0` to avoid wasted Insights queries.
        Returns [{"name": ..., "stored_bytes": ...}, ...].
        """
        kwargs: Dict = {"limit": 50}
        if prefix:
            kwargs["logGroupNamePrefix"] = prefix

        groups: List[Dict] = []
        paginator = self._logs.get_paginator("describe_log_groups")
        for page in paginator.paginate(**kwargs):
            for lg in page.get("logGroups", []):
                if (lg.get("storedBytes") or 0) == 0:
                    continue
                groups.append({
                    "name": lg["logGroupName"],
                    "stored_bytes": lg.get("storedBytes", 0),
                })
                if len(groups) >= max_groups:
                    return groups
        return groups

    # -- Insights query runner ----------------------------------------------

    def _run_queries(
        self,
        log_groups: List[Dict],
        start_time: datetime,
        end_time: datetime,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Tuple[List[Dict], List[Dict]]:
        """Run Insights queries across groups in batches, normalize results.

        Returns finding dicts plus structured permission failures keyed by
        log_group_name.
        """
        all_findings: List[Dict] = []
        permission_error_details: List[Dict] = []
        total = len(log_groups)
        done = 0

        # Process in batches to respect AWS concurrent-query limits.
        for i in range(0, total, _MAX_CONCURRENT_QUERIES):
            batch = log_groups[i:i + _MAX_CONCURRENT_QUERIES]
            query_ids: List[Tuple[str, str]] = []  # (query_id, log_group_name)

            # Kick off all queries in the batch
            for lg in batch:
                try:
                    resp = self._logs.start_query(
                        logGroupName=lg["name"],
                        startTime=int(start_time.timestamp()),
                        endTime=int(end_time.timestamp()),
                        queryString=INSIGHTS_QUERY,
                        limit=50,
                    )
                    query_ids.append((resp["queryId"], lg["name"]))
                except Exception as exc:
                    logger.warning("start_query failed for %s: %s", lg["name"], exc)
                    if self._is_permission_error(exc):
                        permission_error_details.append(
                            self._permission_error_detail(
                                log_group_name=lg["name"],
                                exc=exc,
                            )
                        )
                    done += 1
                    if progress_callback:
                        progress_callback(done, total, lg["name"])

            # Poll each until complete
            for query_id, lg_name in query_ids:
                results = self._poll_query(query_id)
                if results:
                    grouped = group_findings(results)
                    for finding in grouped:
                        finding["log_group_name"] = lg_name
                        finding["severity"] = classify_severity(
                            finding.get("sample_message") or finding.get("error_pattern") or ""
                        )
                        all_findings.append(finding)
                done += 1
                if progress_callback:
                    progress_callback(done, total, lg_name)

        return all_findings, permission_error_details

    @staticmethod
    def _is_permission_error(exc: Exception) -> bool:
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            return code in (
                "AccessDenied",
                "AccessDeniedException",
                "UnauthorizedAccess",
                "AuthorizationError",
            )
        msg = str(exc).lower()
        return any(tok in msg for tok in (
            "accessdenied",
            "unauthorized",
            "not authorized",
            "authorizationerror",
        ))

    def _permission_error_detail(self, log_group_name: str, exc: Exception) -> Dict:
        code = type(exc).__name__
        message = str(exc)
        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {})
            code = error.get("Code") or code
            message = error.get("Message") or message
        return {
            "type": "permission_denied",
            "service": "Logs Insights",
            "region": self.region,
            "code": code,
            "message": f"logs:StartQuery failed for {log_group_name}: {message}",
            "resource_name": log_group_name,
            "resource_types": ["AWS::Logs::LogGroup"],
            "suggestion": (
                "Add CloudWatch Logs Insights permissions such as logs:StartQuery, "
                "logs:GetQueryResults, and logs:StopQuery to the scan role, then rerun the scan."
            ),
        }

    def _poll_query(self, query_id: str) -> List[List[Dict[str, str]]]:
        """Poll GetQueryResults with exponential backoff until complete."""
        waited = 0.0
        interval = _QUERY_POLL_INTERVAL
        while waited < _QUERY_POLL_MAX_WAIT:
            try:
                resp = self._logs.get_query_results(queryId=query_id)
            except Exception as exc:
                logger.warning("get_query_results failed: %s", exc)
                return []

            status = resp.get("status")
            if status == "Complete":
                return resp.get("results", [])
            if status in ("Failed", "Cancelled", "Timeout"):
                logger.info("Query %s ended with status %s", query_id, status)
                return []

            time.sleep(interval)
            waited += interval
            interval = min(interval * 1.5, 5.0)

        # Timed out locally — try to stop the query
        try:
            self._logs.stop_query(queryId=query_id)
        except Exception:
            pass
        return []

    # -- Persistence ---------------------------------------------------------

    def _create_scan_record(self, account_id: str, time_window_hours: int) -> str:
        scan = _storage_create(
            "log-scans",
            {
                "account_id": account_id,
                "region": self.region,
                "time_window_hours": time_window_hours,
                "status": "running",
            },
        )
        return scan["id"]

    def _complete_scan_record(
        self,
        scan_id: str,
        log_groups_scanned: int,
        findings_count: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        scan = _storage_get("log-scans", scan_id)
        if not scan:
            return
        scan.update(
            {
                "log_groups_scanned": log_groups_scanned,
                "findings_count": findings_count,
                "status": status,
                "error_message": error_message,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        _storage_update("log-scans", scan_id, scan)

    def _persist_findings(self, scan_id: str, findings: List[Dict]) -> None:
        """Link + persist findings rows."""
        if not findings:
            return
        resources = _core_resources()
        for f in findings:
            link = _match_log_group(f["log_group_name"], resources, self._logs, self.region)
            _storage_create(
                "log-findings",
                {
                    "scan_id": scan_id,
                    "log_group_name": f["log_group_name"],
                    "error_pattern": f.get("error_pattern"),
                    "severity": f.get("severity") or "medium",
                    "occurrence_count": f.get("occurrence_count") or 0,
                    "first_seen": f.get("first_seen"),
                    "last_seen": f.get("last_seen"),
                    "sample_message": f.get("sample_message"),
                    "resource_id": link["resource_id"] if link else None,
                    "resource_type": link["resource_type"] if link else None,
                    "service_name": link["service_name"] if link else None,
                    "link_status": "linked" if link else "unlinked",
                },
            )

    # =======================================================================
    # On-demand AI analysis
    # =======================================================================

    def analyze_finding(self, finding_id: str, model_alias: str = "sonnet") -> str:
        """Run Bedrock root-cause analysis on a single finding.

        Gives the model tool-use access (fetch_log_events, describe_lambda_function,
        get_cloudwatch_metric, get_resource_detail) so it can investigate instead
        of just guessing from the short sample in the prompt. Persists the final
        analysis onto the finding row.
        """
        # Capture everything we need from the ORM row *before* leaving the
        # DB session — the model interactions + tool loop can take a while.
        finding_payload = _storage_get("log-findings", finding_id)
        if not finding_payload:
            raise ValueError(f"LogFinding {finding_id} not found")
        finding = _objectify(finding_payload)
        samples = self._fetch_samples(finding)
        resource = _objectify(_storage_get_core_resource(finding.resource_id)) if getattr(finding, "resource_id", None) else None
        prompt = self._build_prompt(finding, resource, samples)

        # Give Bedrock the tool set + a dispatcher that closes over this
        # finding's context (region, session, log group window).
        ctx = AnalysisContext(finding=finding, region=self.region, session=self._session)

        def _dispatch(name, args):
            return tool_result_json(dispatch_tool(name, args or {}, ctx))

        analysis = converse_with_tools(
            prompt=prompt,
            tools=tool_specs(),
            tool_dispatcher=_dispatch,
            model_alias=model_alias,
            region=self.region,
            system_prompt=(
                "You are an AWS infrastructure SRE. Your job is to produce a "
                "grounded, specific root-cause report for a CloudWatch log error. "
                "You MUST use the tools to fetch real data before concluding — "
                "never rely on generic guesses. Typical investigation: "
                "(1) fetch more log events to find the real stack trace, "
                "(2) if it's a Lambda log group, call describe_lambda_function "
                "to get runtime/memory/timeout/VPC/env, "
                "(3) pull Invocations/Errors/Duration/Throttles metrics to "
                "quantify impact, (4) if linked, get_resource_detail for tags. "
                "Cite the concrete values you observed (error class, line number, "
                "error rate, memory, timeout) in your report."
            ),
        )

        finding_payload["ai_analysis"] = analysis
        finding_payload["ai_analyzed_at"] = datetime.now(timezone.utc)
        _storage_update("log-findings", finding_id, finding_payload)

        return analysis

    # -- Sample fetch --------------------------------------------------------

    def _fetch_samples(self, finding: Any) -> List[str]:
        cache_key = f"log_samples:{finding.id}"
        cached = cache_manager.get(cache_key)
        if cached is not None:
            return cached

        start_ts = finding.first_seen or (datetime.now(timezone.utc) - timedelta(hours=24))
        end_ts = finding.last_seen or datetime.now(timezone.utc)
        keyword = self._extract_keyword(finding.sample_message or "")

        params = {
            "logGroupName": finding.log_group_name,
            "startTime": int(start_ts.timestamp() * 1000),
            "endTime": int(end_ts.timestamp() * 1000),
            "limit": _SAMPLE_FETCH_LIMIT,
        }
        if keyword:
            params["filterPattern"] = f'"{keyword}"'

        try:
            resp = self._logs.filter_log_events(**params)
        except Exception as exc:
            logger.warning("filter_log_events failed for %s: %s", finding.log_group_name, exc)
            return []

        lines = [e.get("message", "").rstrip() for e in resp.get("events", []) if e.get("message")]
        cache_manager.set(cache_key, lines, ttl=TTL_LOG_SAMPLES)
        return lines

    @staticmethod
    def _extract_keyword(raw_message: str) -> str:
        """Pick a meaningful keyword from a raw log line for filterPattern.

        We avoid the normalized pattern (UUIDs/IPs have been masked) and
        instead grab the first uppercase/error-looking token.
        """
        if not raw_message:
            return ""
        import re
        # Prefer the first ERROR/Exception-ish word
        m = re.search(r"\b([A-Z][A-Za-z]*(?:Error|Exception|Fatal|Warning))\b", raw_message)
        if m:
            return m.group(1)
        # Otherwise the first multi-letter uppercase-ish word
        m = re.search(r"\b([A-Z]{3,}|[A-Z][a-z]+[A-Z][A-Za-z]+)\b", raw_message)
        return m.group(1) if m else ""

    # -- Prompt --------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        finding: Any,
        resource: Optional[Any],
        samples: List[str],
    ) -> str:
        lines: List[str] = [
            "Analyze these CloudWatch log errors and provide:",
            "1. Root cause - what is most likely causing this error",
            "2. Impact - what is the blast radius of this issue",
            "3. Suggested fix - concrete steps to resolve",
            "4. Priority - how urgently should this be addressed and why",
            "",
            f"Log Group: {finding.log_group_name}",
        ]
        if resource is not None:
            lines.append(
                f'Resource: {resource.resource_type} "{resource.resource_id}" ({resource.region})'
            )
        lines.append(
            f'Error pattern: "{finding.error_pattern}" '
            f"({finding.occurrence_count} occurrences, severity={finding.severity})"
        )
        lines.append("")
        lines.append("Sample log lines:")
        if samples:
            lines.extend(samples[:_SAMPLE_FETCH_LIMIT])
        else:
            lines.append("(no sample lines available)")
        return "\n".join(lines)

    # =======================================================================
    # Helpers
    # =======================================================================

    def _get_account_id(self) -> str:
        try:
            return self._sts.get_caller_identity()["Account"]
        except Exception:
            return "unknown"


def _storage_create(collection: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = request_core(
        "POST",
        f"/api/v1/storage/bluearch/{collection}",
        service_token=True,
        json={"payload": _jsonable(payload)},
        timeout=10.0,
    )
    return record.get("payload", record)


def _storage_get(collection: str, record_key: str) -> dict[str, Any] | None:
    try:
        record = request_core(
            "GET",
            f"/api/v1/storage/bluearch/{collection}/{record_key}",
            service_token=True,
            timeout=10.0,
        )
    except Exception:
        return None
    return record.get("payload", record)


def _storage_update(collection: str, record_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = request_core(
        "PUT",
        f"/api/v1/storage/bluearch/{collection}/{record_key}",
        service_token=True,
        json={"payload": _jsonable(payload)},
        timeout=10.0,
    )
    return record.get("payload", record)


def _storage_get_core_resource(record_key: str) -> dict[str, Any] | None:
    try:
        record = request_core(
            "GET",
            f"/api/v1/storage/core/resources/{record_key}",
            service_token=True,
            timeout=10.0,
        )
    except Exception:
        return None
    return record.get("payload", record)


def _core_resources() -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    target = _CORE_RESOURCE_SCAN_LIMIT
    offset = 0
    total: int | None = None

    while len(resources) < target and (total is None or offset < total):
        page_limit = min(_CORE_RESOURCE_PAGE_SIZE, target - len(resources))
        payload = request_core("GET", f"/api/v1/resources?limit={page_limit}&offset={offset}", timeout=10.0)
        if not isinstance(payload, dict):
            break
        items = payload.get("items", [])
        if not isinstance(items, list) or not items:
            break
        resources.extend(items)
        raw_total = payload.get("total")
        total = raw_total if isinstance(raw_total, int) else len(resources)
        offset += len(items)

    return resources


def _match_log_group(
    log_group_name: str,
    resources: list[dict[str, Any]],
    logs_client,
    region: Optional[str],
) -> Optional[dict[str, str]]:
    for pattern, service_name, resource_type in _NAMING_PATTERNS:
        match = pattern.match(log_group_name)
        if not match:
            continue
        resource = _find_resource(resources, service_name, resource_type, match.group(1), region)
        return _resource_link(resource) if resource else None

    try:
        tags = logs_client.list_tags_for_resource(
            resourceArn=f"arn:aws:logs:{region or '*'}:*:log-group:{log_group_name}"
        ).get("tags", {}) or {}
    except Exception:
        tags = {}
    for key in ("ResourceId", "ServiceName", "aws:cloudformation:stack-name", "Name"):
        candidate = tags.get(key)
        if not candidate:
            continue
        resource = _find_resource_by_identifier(resources, candidate, region)
        if resource:
            return _resource_link(resource)
    return None


def _find_resource(
    resources: list[dict[str, Any]],
    service_name: str,
    resource_type: str,
    identifier: str,
    region: Optional[str],
) -> Optional[dict[str, Any]]:
    scoped = [
        resource
        for resource in resources
        if resource.get("service_name") == service_name
        and (not region or resource.get("region") == region)
        and (not resource_type or resource.get("resource_type") == resource_type)
    ]
    return _find_resource_by_identifier(scoped, identifier, region=None)


def _find_resource_by_identifier(
    resources: list[dict[str, Any]],
    identifier: str,
    region: Optional[str],
) -> Optional[dict[str, Any]]:
    for resource in resources:
        if region and resource.get("region") != region:
            continue
        resource_id = str(resource.get("resource_id") or "")
        resource_arn = str(resource.get("resource_arn") or "")
        if resource_id == identifier or resource_arn == identifier or resource_arn.endswith(identifier) or identifier in resource_id:
            return resource
    return None


def _resource_link(resource: dict[str, Any]) -> dict[str, str]:
    return {
        "resource_id": str(resource.get("id") or ""),
        "resource_type": str(resource.get("resource_type") or ""),
        "service_name": str(resource.get("service_name") or ""),
    }


def _objectify(payload: dict[str, Any] | None) -> Any:
    payload = dict(payload or {})
    for key in ("first_seen", "last_seen", "detected_at", "ai_analyzed_at", "created_at", "updated_at"):
        if isinstance(payload.get(key), str):
            try:
                parsed = datetime.fromisoformat(payload[key].replace("Z", "+00:00"))
                payload[key] = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return SimpleNamespace(**payload)


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
