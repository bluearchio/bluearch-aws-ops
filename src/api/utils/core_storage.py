"""Small helpers for bluearch-core storage records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from utils.core_client import CoreRuntimeError, request_core


class StorageObject(SimpleNamespace):
    """Attribute and mapping-style wrapper for core storage payloads."""

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        return dict(vars(self))


def storage_path(namespace: str, collection: str, record_key: str | None = None) -> str:
    path = f"/api/v1/storage/{namespace}/{collection}"
    if record_key:
        path = f"{path}/{record_key}"
    return path


def payload_from_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    payload.setdefault("record_key", (record or {}).get("record_key") or payload.get("id"))
    return payload


def list_records(
    namespace: str,
    collection: str,
    *,
    filters: list[tuple[str, str]] | None = None,
    limit: int = 10000,
    offset: int = 0,
    order_by: str | None = None,
    descending: bool = True,
) -> list[dict[str, Any]]:
    params: list[tuple[str, str | int]] = [
        ("limit", limit),
        ("offset", offset),
        ("descending", str(descending).lower()),
    ]
    if order_by:
        params.append(("order_by", order_by))
    for key, value in filters or []:
        params.append(("filter", f"{key}={value}"))
    records = request_core(
        "GET",
        storage_path(namespace, collection),
        service_token=True,
        params=params,
        timeout=20.0,
    )
    return [payload_from_record(record) for record in records or []]


def list_all_records(
    namespace: str,
    collection: str,
    *,
    filters: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    limit = 10000
    offset = 0
    results: list[dict[str, Any]] = []
    while True:
        rows = list_records(namespace, collection, filters=filters, limit=limit, offset=offset)
        results.extend(rows)
        if len(rows) < limit:
            break
        offset += limit
    return results


def list_objects(
    namespace: str,
    collection: str,
    *,
    filters: list[tuple[str, str]] | None = None,
) -> list[StorageObject]:
    return [to_object(record) for record in list_all_records(namespace, collection, filters=filters)]


def create_record(namespace: str, collection: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = request_core(
        "POST",
        storage_path(namespace, collection),
        service_token=True,
        json={"payload": drop_none(payload)},
        timeout=20.0,
    )
    return payload_from_record(record)


def update_record(namespace: str, collection: str, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    record_key = record.get("record_key") or record.get("id")
    if not record_key:
        raise RuntimeError(f"Cannot update {collection} without a record key")
    response = request_core(
        "PUT",
        storage_path(namespace, collection, str(record_key)),
        service_token=True,
        json={"payload": drop_none({**record, **payload})},
        timeout=20.0,
    )
    return payload_from_record(response)


def delete_record(namespace: str, collection: str, record: dict[str, Any]) -> bool:
    record_key = record.get("record_key") or record.get("id")
    if not record_key:
        return False
    request_core(
        "DELETE",
        storage_path(namespace, collection, str(record_key)),
        service_token=True,
        timeout=20.0,
    )
    return True


def delete_records(namespace: str, collection: str, records: list[dict[str, Any]]) -> int:
    return sum(1 for record in records if delete_record(namespace, collection, record))


def get_first_record(
    namespace: str,
    collection: str,
    *,
    filters: list[tuple[str, str]],
) -> dict[str, Any] | None:
    rows = list_records(namespace, collection, filters=filters, limit=1)
    return rows[0] if rows else None


def upsert_by_filter(
    namespace: str,
    collection: str,
    *,
    filters: list[tuple[str, str]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    existing = get_first_record(namespace, collection, filters=filters)
    if existing:
        return update_record(namespace, collection, existing, payload)
    try:
        return create_record(namespace, collection, payload)
    except CoreRuntimeError:
        existing = get_first_record(namespace, collection, filters=filters)
        if existing:
            return update_record(namespace, collection, existing, payload)
        raise


def resource_payload(resource_data: dict[str, Any], *, default_account_id: str | None = None) -> dict[str, Any]:
    arn = resource_data.get("resource_arn", "")
    account_id = resource_data.get("account_id") or default_account_id or ""
    if arn.startswith("arn:aws:"):
        arn_parts = arn.split(":")
        if len(arn_parts) >= 5 and arn_parts[4].isdigit():
            account_id = arn_parts[4]
    return {
        "resource_arn": arn,
        "account_id": account_id,
        "resource_type": resource_data.get("resource_type", ""),
        "region": resource_data.get("region", "global"),
        "service_name": resource_data.get("service_name", ""),
        "current_tags": coerce_json_value(resource_data.get("current_tags", {})),
        "metadata_json": coerce_json_value(resource_data.get("metadata_json", resource_data.get("metadata", {}))),
        "resource_id": resource_data.get("resource_id", ""),
        "created_at": format_datetime(resource_data.get("created_at")),
        "last_scanned_at": datetime.now(timezone.utc).isoformat(),
        "lifecycle_state": resource_data.get("lifecycle_state", "active"),
    }


def coerce_json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def format_datetime(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def to_object(payload: dict[str, Any]) -> StorageObject:
    return StorageObject(**dict(payload or {}))
