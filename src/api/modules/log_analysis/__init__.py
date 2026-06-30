"""Log Analysis module — CloudWatch Logs scanning + AI root-cause analysis.

Top-level entry points:
- LogAnalysisService.run_scan() — orchestrates scan end-to-end
- LogAnalysisService.analyze_finding() — fetches samples + calls Bedrock
"""

from modules.log_analysis.service import LogAnalysisService
from modules.log_analysis.severity import classify_severity
from modules.log_analysis.queries import (
    INSIGHTS_QUERY,
    normalize_message,
    group_findings,
)

__all__ = [
    "LogAnalysisService",
    "classify_severity",
    "INSIGHTS_QUERY",
    "normalize_message",
    "group_findings",
]
