"""CloudWatch Logs Insights query templates + result normalization."""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Insights query templates
# ---------------------------------------------------------------------------

# Generic application-log error detection. Server-side filter + stats so we
# pay for scanned bytes only once per log group.
INSIGHTS_QUERY = (
    "fields @timestamp, @message, @logStream\n"
    "| filter @message like /(?i)(ERROR|Exception|FATAL|CRITICAL|Traceback|"
    "OutOfMemory|OOMKilled|SIGKILL|SIGSEGV|timeout|connection refused)/\n"
    "| stats count(*) as occurrence_count, min(@timestamp) as first_seen, "
    "max(@timestamp) as last_seen by @message\n"
    "| sort occurrence_count desc\n"
    "| limit 50"
)


# ---------------------------------------------------------------------------
# Python-side normalization (addresses high-cardinality @message grouping)
# ---------------------------------------------------------------------------

# Strip variable data that breaks grouping. Order matters: more specific
# patterns first.
_NORMALIZE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # ISO-8601 timestamps (2026-04-20T12:34:56.789Z and variants)
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<TS>"),
    # UUIDs
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    # AWS request IDs (hex 32)
    (re.compile(r"\b[0-9a-fA-F]{32}\b"), "<HEX>"),
    # IPv4 addresses
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
    # Long numeric IDs (order IDs, epoch ms, etc.)
    (re.compile(r"\b\d{6,}\b"), "<N>"),
]

_MAX_NORMALIZED_LENGTH = 200


def normalize_message(raw: str) -> str:
    """Strip variable data (UUIDs, timestamps, IPs, numeric IDs) so similar
    error messages collapse to the same pattern. Truncates to 200 chars.

    Example:
        >>> normalize_message("ERROR 2026-04-20T12:00:00Z req-abc-123 from 10.0.0.1")
        'ERROR <TS> req-abc-<N> from <IP>'
    """
    if not raw:
        return ""
    s = raw
    for pattern, placeholder in _NORMALIZE_PATTERNS:
        s = pattern.sub(placeholder, s)
    # Collapse internal whitespace to single spaces
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > _MAX_NORMALIZED_LENGTH:
        s = s[:_MAX_NORMALIZED_LENGTH]
    return s


def _parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    """Parse Insights-returned timestamps (usually ISO-8601)."""
    if not raw:
        return None
    try:
        # Insights timestamps look like "2026-04-20 12:34:56.789"
        return datetime.fromisoformat(raw.replace(" ", "T").rstrip("Z"))
    except (ValueError, TypeError):
        return None


def group_findings(
    raw_results: List[List[Dict[str, str]]],
) -> List[Dict]:
    """Normalize + group raw Insights result rows by pattern.

    Insights returns a list of rows, each a list of {"field": ..., "value": ...}.
    We normalize the `@message` field into an `error_pattern` and merge rows
    that share the same pattern (summing occurrence_count, taking
    min(first_seen) / max(last_seen)).

    Returns a list of dicts suitable for building LogFinding rows.
    """
    groups: Dict[str, Dict] = {}

    for row in raw_results:
        fields = {item.get("field"): item.get("value") for item in row}
        raw_msg = fields.get("@message") or ""
        if not raw_msg:
            continue

        pattern = normalize_message(raw_msg)
        if not pattern:
            continue

        try:
            count = int(fields.get("occurrence_count") or 0)
        except (TypeError, ValueError):
            count = 0

        first_seen = _parse_timestamp(fields.get("first_seen"))
        last_seen = _parse_timestamp(fields.get("last_seen"))

        existing = groups.get(pattern)
        if existing is None:
            groups[pattern] = {
                "error_pattern": pattern,
                "sample_message": raw_msg,
                "occurrence_count": count,
                "first_seen": first_seen,
                "last_seen": last_seen,
            }
        else:
            existing["occurrence_count"] += count
            if first_seen and (existing["first_seen"] is None or first_seen < existing["first_seen"]):
                existing["first_seen"] = first_seen
            if last_seen and (existing["last_seen"] is None or last_seen > existing["last_seen"]):
                existing["last_seen"] = last_seen

    # Sort most-common first so the top findings lead the UI
    return sorted(groups.values(), key=lambda g: g["occurrence_count"], reverse=True)
