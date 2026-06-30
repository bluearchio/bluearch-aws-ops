"""Helpers for product persistence through bluearch-core storage APIs."""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel

from utils.core_client import request_core


def list_storage_payloads(
    namespace: str,
    collection: str,
    *,
    limit: int = 100,
    offset: int = 0,
    filters: Iterable[tuple[str, Any]] | None = None,
    order_by: str | None = None,
    descending: bool = True,
) -> list[dict[str, Any]]:
    params: list[tuple[str, Any]] = [
        ("limit", limit),
        ("offset", offset),
        ("descending", str(descending).lower()),
    ]
    if order_by:
        params.append(("order_by", order_by))
    for field, value in filters or []:
        if value is not None:
            params.append(("filter", f"{field}={value}"))
    records = request_core(
        "GET",
        f"/api/v1/storage/{namespace}/{collection}",
        service_token=True,
        params=params,
    )
    return [record_payload(record) for record in records or []]


def get_storage_payload(namespace: str, collection: str, record_key: str) -> dict[str, Any]:
    record = request_core(
        "GET",
        f"/api/v1/storage/{namespace}/{collection}/{record_key}",
        service_token=True,
    )
    return record_payload(record)


def create_storage_payload(
    namespace: str,
    collection: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    record = request_core(
        "POST",
        f"/api/v1/storage/{namespace}/{collection}",
        service_token=True,
        json={"payload": payload},
    )
    return record_payload(record)


def update_storage_payload(
    namespace: str,
    collection: str,
    record_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    record = request_core(
        "PUT",
        f"/api/v1/storage/{namespace}/{collection}/{record_key}",
        service_token=True,
        json={"payload": payload},
    )
    return record_payload(record)


def delete_storage_payload(namespace: str, collection: str, record_key: str) -> None:
    request_core(
        "DELETE",
        f"/api/v1/storage/{namespace}/{collection}/{record_key}",
        service_token=True,
    )


def record_payload(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {}
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else record


def model_payload(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)
