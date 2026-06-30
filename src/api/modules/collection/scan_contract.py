"""Unified scan result contract — both CLIs must produce identical Resource rows.

This module defines the required fields for a valid resource dict and provides
validation. Both `bluearch scan` and `tag-manager scan` output must pass
this validation before being written to the shared database.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger_config import log
from utils.core_client import request_core


# ---------------------------------------------------------------------------
# Required fields for every resource dict produced by a collector.
# Both the BlueArch CLI and the Tag Manager CLI must produce resource dicts
# containing ALL of these keys. The shared SQLite database relies on this
# contract — if a field is missing, the resource row will be incomplete and
# cross-CLI queries may break.
# ---------------------------------------------------------------------------
REQUIRED_RESOURCE_FIELDS = {
    "resource_arn",      # Full ARN (unique identifier)
    "resource_type",     # CloudFormation type (e.g. AWS::EC2::Instance)
    "service_name",      # Short service name (e.g. ec2, rds, iam)
    "region",            # AWS region or "global" for IAM
    "account_id",        # 12-digit AWS account ID
    "resource_id",       # Service-specific ID (e.g. i-1234567890abcdef0)
    "current_tags",      # Dict of tag key-value pairs (may be {} or None)
    "metadata_json",     # Service-specific metadata dict (may be {} or None)
}

# Optional fields that enrich the resource row but are not always available
OPTIONAL_RESOURCE_FIELDS = {
    "created_at",        # When the resource was created (datetime)
}


def validate_resource_dict(resource: Dict[str, Any]) -> List[str]:
    """Validate a resource dict against the scan contract.

    Every collector (BlueArch and Tag Manager) must produce dicts that pass
    this validation before writing to the shared SQLite database.

    Returns a list of error messages. Empty list means valid.
    """
    errors = []

    # Fields that must be present AND have a truthy (non-empty) value
    _MUST_BE_TRUTHY = {
        "resource_arn", "resource_type", "service_name",
        "region", "account_id", "resource_id",
    }

    # Fields that must be present as keys but may be None / empty dict
    _PRESENCE_ONLY = {"current_tags", "metadata_json"}

    for field in REQUIRED_RESOURCE_FIELDS:
        if field in _MUST_BE_TRUTHY:
            if field not in resource or not resource[field]:
                errors.append(f"Missing required field: {field}")
        elif field in _PRESENCE_ONLY:
            if field not in resource:
                errors.append(f"Missing required field: {field}")

    # ARN format check
    arn = resource.get("resource_arn", "")
    if arn and not arn.startswith("arn:aws:"):
        errors.append(f"Invalid ARN format: {arn}")

    # Account ID format check (must be 12 digits when present)
    account_id = resource.get("account_id", "")
    if account_id and (not account_id.isdigit() or len(account_id) != 12):
        if len(account_id) > 0:
            errors.append(f"Invalid account_id format: {account_id}")

    return errors


def validate_scan_output(resources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate a batch of resource dicts from a scan.

    Returns summary with valid count, error count, and sample errors.
    """
    valid = 0
    invalid = 0
    sample_errors = []

    for r in resources:
        errors = validate_resource_dict(r)
        if errors:
            invalid += 1
            if len(sample_errors) < 5:
                sample_errors.append({
                    "resource_arn": r.get("resource_arn", "?"),
                    "errors": errors,
                })
        else:
            valid += 1

    return {
        "valid": valid,
        "invalid": invalid,
        "total": len(resources),
        "sample_errors": sample_errors,
    }


def validate_scan_result(result: Dict[str, Any]) -> bool:
    """Validate the overall scan result dict returned by run_local_scan().

    Checks that the result dict contains the expected top-level keys
    produced by a successful scan. Returns True if the result is
    structurally valid, False otherwise.

    Args:
        result: The summary dict returned by run_local_scan().

    Returns:
        True if all expected keys exist and have sensible types.
    """
    EXPECTED_KEYS = {
        "account_id": str,
        "account_name": str,
        "regions_scanned": int,
        "services_scanned": int,
        "resources_found": int,
        "errors": list,
    }

    for key, expected_type in EXPECTED_KEYS.items():
        if key not in result:
            log.debug(f"Scan result missing expected key: {key}")
            return False
        if not isinstance(result[key], expected_type):
            log.debug(
                f"Scan result key '{key}' has type {type(result[key]).__name__}, "
                f"expected {expected_type.__name__}"
            )
            return False

    if result.get("error"):
        log.debug(f"Scan result contains error: {result['error']}")
        return False

    return True


def can_skip_scan(max_age_minutes: int = 5) -> Optional[Dict[str, Any]]:
    """Check if a recent scan exists that's fresh enough to reuse.

    Used by the --skip-scan flag. Returns the scan info dict if a fresh
    scan is available, None otherwise.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_minutes * 60)

    rows = request_core(
        "GET",
        "/api/v1/storage/core/scan-history",
        service_token=True,
        params=[("limit", 50), ("order_by", "completed_at"), ("descending", "true")],
        timeout=10.0,
    )
    completed_statuses = {"completed", "completed_with_errors"}
    latest = next(
        (
            _payload_from_record(row)
            for row in rows or []
            if _payload_from_record(row).get("status") in completed_statuses
        ),
        None,
    )

    if not latest or not latest.get("completed_at"):
        return None

    completed_at = _parse_core_datetime(latest.get("completed_at"))
    if not completed_at:
        return None

    completed_ts = completed_at.timestamp()
    if completed_ts < cutoff:
        return None

    age_minutes = int((datetime.now(timezone.utc).timestamp() - completed_ts) / 60)

    return {
        "scan_id": latest.get("id"),
        "collected_by": latest.get("collected_by"),
        "scan_mode": latest.get("scan_mode"),
        "completed_at": completed_at.isoformat(),
        "resources_found": latest.get("resources_found"),
        "age_minutes": age_minutes,
    }


def _payload_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    return payload


def _parse_core_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
