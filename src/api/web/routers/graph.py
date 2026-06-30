"""Graph / resource-map API endpoints backed by bluearch-core."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.core_client import request_core
from web.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])
CORE_RESOURCE_PAGE_SIZE = 1000
CORE_RESOURCE_SCAN_LIMIT = 10000

SERVICE_CATEGORIES = {
    "ec2": {"index": 0, "color": "#f97316"},
    "s3": {"index": 1, "color": "#22c55e"},
    "lambda": {"index": 2, "color": "#a855f7"},
    "rds": {"index": 3, "color": "#3b82f6"},
    "dynamodb": {"index": 4, "color": "#f59e0b"},
    "ecs": {"index": 5, "color": "#14b8a6"},
    "elb": {"index": 6, "color": "#06b6d4"},
    "elbv2": {"index": 6, "color": "#06b6d4"},
    "sns": {"index": 7, "color": "#e11d48"},
    "sqs": {"index": 8, "color": "#8b5cf6"},
    "cloudwatch": {"index": 9, "color": "#ef4444"},
    "eks": {"index": 10, "color": "#0ea5e9"},
    "elasticache": {"index": 11, "color": "#dc2626"},
    "iam": {"index": 12, "color": "#eab308"},
}


class GraphNodeResponse(BaseModel):
    id: str
    name: str
    service: str
    service_name: str
    resource_type: str
    resource_id: str
    region: str
    account_id: str
    category: int = 0
    symbol_size: int = 20
    value: int = 1
    tags: Optional[dict] = None
    recommendation_count: int = 0


class GraphEdgeResponse(BaseModel):
    source: str
    target: str
    relationship_type: str


class GraphResponse(BaseModel):
    nodes: List[GraphNodeResponse] = []
    edges: List[GraphEdgeResponse] = []
    categories: List[dict] = []
    stats: dict = {}
    truncated: bool = False


class GraphFiltersResponse(BaseModel):
    services: List[str] = []
    regions: List[str] = []
    relationship_types: List[str] = []
    account_ids: List[str] = []


def _core_resources(**params) -> dict:
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    suffix = f"?{query}" if query else ""
    return request_core("GET", f"/api/v1/resources{suffix}", timeout=10.0)


def _core_all_resources_payload(*, max_items: int = CORE_RESOURCE_SCAN_LIMIT, **params) -> dict:
    resources: list[dict] = []
    offset = 0
    total: int | None = None
    target = max(1, min(max_items, CORE_RESOURCE_SCAN_LIMIT))
    while len(resources) < target:
        page_limit = min(CORE_RESOURCE_PAGE_SIZE, target - len(resources))
        payload = _core_resources(**params, limit=page_limit, offset=offset)
        if total is None and isinstance(payload.get("total"), int):
            total = payload["total"]
        items = payload.get("items", [])
        if not items:
            break
        resources.extend(items)
        offset += len(items)
        if len(items) < page_limit or (isinstance(total, int) and offset >= total):
            break
    return {"items": resources, "total": total if total is not None else len(resources)}


def _core_all_resources(*, max_items: int = CORE_RESOURCE_SCAN_LIMIT, **params) -> list[dict]:
    return _core_all_resources_payload(max_items=max_items, **params)["items"]


def _core_relationships(limit: int = 10000) -> list[dict]:
    rows = request_core(
        "GET",
        f"/api/v1/storage/core/resource-relationships?{urlencode({'limit': limit})}",
        service_token=True,
        timeout=10.0,
    )
    return [row.get("payload", row) for row in rows or []]


def _tags(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _node(resource: dict, degree: int = 0, rec_count: int = 0) -> GraphNodeResponse:
    service = resource.get("service_name") or "unknown"
    cat = SERVICE_CATEGORIES.get(service, {"index": len(SERVICE_CATEGORIES), "color": "#6b7280"})
    name = resource.get("resource_id") or str(resource.get("resource_arn") or resource.get("id")).split("/")[-1]
    return GraphNodeResponse(
        id=resource.get("resource_arn") or resource.get("id"),
        name=name,
        service=service,
        service_name=service,
        resource_type=resource.get("resource_type") or "",
        resource_id=resource.get("resource_id") or "",
        region=resource.get("region") or "",
        account_id=resource.get("account_id") or "",
        category=cat["index"],
        symbol_size=min(60, 20 + (4 if rec_count else 0) + min(degree, 8) * 4),
        tags=_tags(resource.get("current_tags")),
        recommendation_count=rec_count,
    )


@router.get("/data", response_model=GraphResponse)
async def get_graph_data(
    service: Optional[str] = None,
    region: Optional[str] = None,
    account_id: Optional[str] = None,
    limit: int = Query(500, le=2000),
    current_user=Depends(get_current_user),
):
    """Get graph data from core resources and relationships."""
    try:
        resources_payload = _core_all_resources_payload(
            service=service,
            region=region,
            account_id=account_id,
            max_items=limit,
        )
        resources = resources_payload["items"]
        relationships = _core_relationships()
        arn_set = {resource.get("resource_arn") for resource in resources if resource.get("resource_arn")}
        edges = [
            GraphEdgeResponse(source=rel.get("source_arn"), target=rel.get("target_arn"), relationship_type=rel.get("relationship_type") or "")
            for rel in relationships
            if rel.get("source_arn") in arn_set and rel.get("target_arn") in arn_set
        ]
        rec_records = request_core("GET", "/api/v1/storage/bluearch/recommendations?limit=10000", service_token=True, timeout=10.0)
        rec_counts = Counter((row.get("payload") or {}).get("resource_id") for row in rec_records or [])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core graph data unavailable: {exc}") from exc
    degree = defaultdict(int)
    for edge in edges:
        degree[edge.source] += 1
        degree[edge.target] += 1
    nodes = [_node(resource, degree.get(resource.get("resource_arn"), 0), rec_counts.get(resource.get("id"), 0)) for resource in resources]
    result = GraphResponse(
        nodes=nodes,
        edges=edges,
        categories=[{"name": key, "color": value["color"]} for key, value in SERVICE_CATEGORIES.items()],
        truncated=bool(resources_payload.get("total", 0) > limit),
        stats={"total_nodes": len(nodes), "total_edges": len(edges), "by_service": dict(Counter(node.service_name for node in nodes))},
    )
    return result


@router.get("/filters", response_model=GraphFiltersResponse)
async def get_graph_filters(_user: Optional[dict] = Depends(get_current_user)):
    """Get available filter options for the graph."""
    try:
        resources = _core_all_resources()
        relationships = _core_relationships()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core graph filters unavailable: {exc}") from exc
    return GraphFiltersResponse(
        services=sorted({row.get("service_name") for row in resources if row.get("service_name")}),
        regions=sorted({row.get("region") for row in resources if row.get("region")}),
        account_ids=sorted({row.get("account_id") for row in resources if row.get("account_id")}),
        relationship_types=sorted({row.get("relationship_type") for row in relationships if row.get("relationship_type")}),
    )


@router.get("/stats")
async def get_graph_stats(_user: Optional[dict] = Depends(get_current_user)):
    """Summary statistics for the resource graph."""
    try:
        summary = request_core("GET", "/api/v1/resources/summary", timeout=5.0)
        relationships = _core_relationships()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core graph stats unavailable: {exc}") from exc
    return {
        "total_resources": summary.get("total", 0),
        "total_relationships": len(relationships),
        "services": len(summary.get("by_service", [])),
        "regions": len(summary.get("by_region", [])),
    }
