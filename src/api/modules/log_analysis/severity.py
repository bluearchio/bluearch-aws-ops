"""Pattern -> severity classifier for log findings."""

import re
from typing import List, Pattern, Tuple


# Severity rules — first match wins. More specific patterns first.
_SEVERITY_RULES: List[Tuple[Pattern, str]] = [
    # CRITICAL — process crashes, OOM, fatal signals
    (re.compile(r"\b(OOMKilled|OutOfMemory|SIGKILL|SIGSEGV|segfault|FATAL|CRITICAL|panic)\b", re.IGNORECASE), "critical"),
    # HIGH — unhandled exceptions, 5xx, connection refused, timeout
    (re.compile(r"\b(Unhandled|UnhandledException|5\d{2}\s|timeout|timed out|connection refused|ECONNREFUSED)\b", re.IGNORECASE), "high"),
    # MEDIUM — handled exceptions, throttling, retry failures
    (re.compile(r"\b(Exception|Traceback|Throttl|RetryError|retry failed)\b", re.IGNORECASE), "medium"),
    # LOW — warnings, deprecation
    (re.compile(r"\b(WARN|warning|deprecat)\b", re.IGNORECASE), "low"),
]

_DEFAULT_SEVERITY = "medium"


def classify_severity(message: str) -> str:
    """Map a raw or normalized log line to a severity bucket.

    Returns one of: critical, high, medium, low.
    Defaults to "medium" when the line matched the generic ERROR filter
    but no specific rule triggers.
    """
    if not message:
        return _DEFAULT_SEVERITY
    for pattern, severity in _SEVERITY_RULES:
        if pattern.search(message):
            return severity
    return _DEFAULT_SEVERITY
