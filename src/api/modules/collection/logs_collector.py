"""Log analysis integrated as a scan-pipeline collector.

Runs as part of `bluearch scan` (and the web Scan Resources button) so users
get log findings in the same workflow as resource discovery — no separate
log-scan flow. Persists LogScan + LogFinding rows as a side effect; returns
zero Resources so it plugs into the existing scanner loop without skewing
resource counts.
"""

import logging
from typing import Optional

from modules.collection.collectors import ServiceCollector
from modules.collection.models import CollectionJob, CollectorResult

logger = logging.getLogger(__name__)


# Defaults tuned for the combined scan: short window + low cap so log
# scanning doesn't dominate runtime or cost. Users who want a deeper sweep
# can still rerun manually through the CLI / API.
DEFAULT_TIME_WINDOW_HOURS = 24
DEFAULT_MAX_GROUPS = 200


class LogsCollector(ServiceCollector):
    """Scan CloudWatch Logs for error patterns in the given region.

    Does NOT return Resource rows — writes directly to the LogScan +
    LogFinding tables. Returning an empty CollectorResult keeps the
    scanner's per-service resource accounting correct.
    """

    def collect(self, job: CollectionJob) -> CollectorResult:
        result = CollectorResult()

        # Lazy import to keep the collectors module lightweight on startup.
        from modules.log_analysis.service import LogAnalysisService

        region = job.region
        if not region:
            # Logs is region-scoped; skip rather than crash if orchestration
            # ever marks it global.
            return result

        try:
            service = LogAnalysisService(region=region, session=job.session)
            scan_summary = service.run_scan(
                time_window_hours=DEFAULT_TIME_WINDOW_HOURS,
                max_groups=DEFAULT_MAX_GROUPS,
                min_severity="low",
            )
            permission_details = scan_summary.get("permission_error_details") or []
            if permission_details:
                for detail in permission_details:
                    enriched = dict(detail)
                    enriched["account_id"] = enriched.get("account_id") or job.account_id
                    result.permission_error_details.append(enriched)
                result.permission_errors += len(permission_details)
        except Exception as exc:
            # Mirror the other collectors' failure mode: record the error
            # and let the scanner continue with the next service/region.
            logger.debug("Logs collector error in %s: %s", region, exc)
            result.errors.append(f"logs/{region}: {exc}")
            if self._is_permission_error_like(exc):
                self._record_permission_error(
                    result,
                    region,
                    "Logs Insights",
                    exc,
                    account_id=job.account_id,
                )

        return result

    @staticmethod
    def _is_permission_error_like(exc: Exception) -> bool:
        """Broad permission-error match (logs:* actions can raise a few
        different ClientError codes)."""
        msg = str(exc).lower()
        return any(tok in msg for tok in (
            "accessdenied",
            "unauthorized",
            "not authorized",
            "authorizationerror",
        ))
