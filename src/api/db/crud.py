"""Legacy DatabaseManager backed by bluearch-core storage APIs.

Provides the same interface as the original PynamoDB-based DatabaseManager
so legacy code in cli/config.py, commons/get.py, and aws/wrappers/ continues
to work without changes.
"""

from typing import Optional, List
from utils.logger_config import log
from utils.core_client import request_core


class _RecommendationCompat:
    """Thin compatibility wrapper over a recommendation payload."""

    def __init__(self, row):
        self.unique_id = _get(row, "unique_id")
        self.recommendation_type = _get(row, "recommendation_type")
        self.region_name = _get(row, "region_name")
        self.account_id = _get(row, "account_id")
        self.account_name = _get(row, "account_name")
        self.last_updated = _get(row, "last_updated")
        self.attributes = _get(row, "attributes") or {}
        self.attribute_values = {
            "unique_id": self.unique_id,
            "recommendation_type": self.recommendation_type,
            "region_name": self.region_name,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "last_updated": str(self.last_updated) if self.last_updated else None,
            "attributes": self.attributes,
        }


class DatabaseManager:
    """Core-backed replacement for the legacy PynamoDB DatabaseManager."""

    def __init__(self):
        self._account_ids = None

    def get_accounts_and_regions(self, account_ids: Optional[List[str]] = None) -> dict:
        result = {}
        accounts = _list_storage("core", "account-status", limit=10000)
        wanted_accounts = set(account_ids or [])
        for account in accounts:
            account_id = account.get("account_id")
            if not account_id:
                continue
            if wanted_accounts and account_id not in wanted_accounts:
                continue
            regions = account.get("regions") if isinstance(account.get("regions"), list) else []
            result[account_id] = {
                "regions": regions,
                "account_name": account.get("account_name") or "Unknown",
            }
        return result

    def populate_accounts_and_regions(self):
        """Populate core account-status records from AWS Organizations / STS."""
        import boto3

        log.debug("Populating accounts and regions...")
        try:
            sts = boto3.client("sts")
            identity = sts.get_caller_identity()
            account_id = identity["Account"]
        except Exception as e:
            log.error(f"Failed to get AWS identity: {e}")
            return

        try:
            org = boto3.client("organizations")
            account_name = org.describe_account(AccountId=account_id)["Account"]["Name"]
        except Exception:
            account_name = account_id

        try:
            ec2 = boto3.client("ec2")
            region_resp = ec2.describe_regions(
                Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
            )
            regions = [r["RegionName"] for r in region_resp["Regions"]]
        except Exception:
            regions = ["us-east-1"]

        target_account_ids = list(self._account_ids or [account_id])
        for target_account_id in target_account_ids:
            target_name = account_name if target_account_id == account_id else target_account_id
            existing = _find_storage_by_field("core", "account-status", "account_id", target_account_id)
            payload = dict(existing or {})
            payload.update({
                "account_id": target_account_id,
                "account_name": payload.get("account_name") or target_name,
                "regions": regions,
                "enabled_for_discovery": True,
                "enabled_for_tagging": payload.get("enabled_for_tagging", False),
                "status": payload.get("status") or "ACTIVE",
            })
            if existing:
                _update_storage("core", "account-status", existing["id"], payload)
            else:
                _create_storage("core", "account-status", payload)

    def get_recommendations(
        self,
        account_id: Optional[str] = None,
        region: Optional[str] = None,
        recommendation_type: Optional[str] = None,
    ) -> list:
        filters = []
        if account_id:
            filters.append(("account_id", account_id))
        if region:
            filters.append(("region_name", region))
        if recommendation_type:
            filters.append(("recommendation_type", recommendation_type))
        rows = _list_storage("bluearch", "recommendations", filters=filters, limit=10000)
        return [_RecommendationCompat(row) for row in rows]

    def get_recommendation_types(self) -> List[str]:
        rows = _list_storage("bluearch", "recommendations", limit=10000)
        return sorted(
            {row.get("recommendation_type") for row in rows if row.get("recommendation_type")}
        )


def _get(row, key: str):
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _list_storage(
    namespace: str,
    collection: str,
    *,
    filters: Optional[List[tuple[str, str]]] = None,
    limit: int = 100,
) -> list[dict]:
    params = [("limit", limit)]
    for field, value in filters or []:
        params.append(("filter", f"{field}={value}"))
    records = request_core(
        "GET",
        f"/api/v1/storage/{namespace}/{collection}",
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [_payload_from_storage_record(record) for record in records or []]


def _find_storage_by_field(
    namespace: str,
    collection: str,
    field: str,
    value: str,
) -> Optional[dict]:
    rows = _list_storage(namespace, collection, filters=[(field, value)], limit=1)
    return rows[0] if rows else None


def _create_storage(namespace: str, collection: str, payload: dict) -> dict:
    record = request_core(
        "POST",
        f"/api/v1/storage/{namespace}/{collection}",
        service_token=True,
        json={"payload": payload},
        timeout=10.0,
    )
    return _payload_from_storage_record(record)


def _update_storage(namespace: str, collection: str, record_id: str, payload: dict) -> dict:
    record = request_core(
        "PUT",
        f"/api/v1/storage/{namespace}/{collection}/{record_id}",
        service_token=True,
        json={"payload": payload},
        timeout=10.0,
    )
    return _payload_from_storage_record(record)


def _payload_from_storage_record(record: dict) -> dict:
    payload = dict(record.get("payload", record) or {})
    payload.setdefault(
        "id",
        record.get("id") or record.get("record_key") or payload.get("id"),
    )
    return payload
