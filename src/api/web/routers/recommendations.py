"""Recommendation endpoints backed by bluearch-core storage."""

import json
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query

from utils.event_hooks import track_event
from utils.core_client import request_core
from web.dependencies import get_current_user
from web.schemas.common import PaginatedResponse
from web.schemas.recommendations import (
    CreateRecommendationNoteRequest,
    RecommendationNoteResponse,
    RecommendationResponse,
    RecommendationSummaryResponse,
    RecommendationTypeCount,
    UpdateRecommendationNoteRequest,
)

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


@router.get("", response_model=PaginatedResponse[RecommendationResponse])
async def list_recommendations(
    current_user=Depends(get_current_user),
    recommendation_type: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """List recommendations with optional filters."""
    try:
        result = _core_list_recommendations(
            recommendation_type=recommendation_type,
            account_id=account_id,
            region=region,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core recommendations unavailable: {exc}") from exc

    _track_recommendation_list(
        current_user, result.items, result.total, page, page_size, recommendation_type, account_id, region
    )
    return result


@router.get("/summary", response_model=RecommendationSummaryResponse)
async def recommendation_summary():
    """Aggregated summary for the dashboard."""
    try:
        return _build_recommendation_summary(_core_recommendation_payloads())
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"bluearch-core recommendation summary unavailable: {exc}"
        ) from exc


@router.get("/types")
async def recommendation_types():
    """List all distinct recommendation types currently stored."""
    try:
        counts: dict[str, int] = {}
        for rec in _core_recommendation_payloads():
            rec_type = rec.get("recommendation_type")
            if rec_type:
                counts[rec_type] = counts.get(rec_type, 0) + 1
        return [
            {"type": rec_type, "count": count}
            for rec_type, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"bluearch-core recommendation types unavailable: {exc}"
        ) from exc


@router.get("/{recommendation_id}", response_model=RecommendationResponse)
async def get_recommendation(recommendation_id: str):
    """Get a single recommendation by ID."""
    try:
        rec = _core_get_payload("recommendations", recommendation_id)
        rec["notes"] = _core_notes_for_recommendation(recommendation_id)
        return _serialize_core_rec(rec)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core recommendation unavailable: {exc}") from exc


@router.get(
    "/{recommendation_id}/notes",
    response_model=list[RecommendationNoteResponse],
)
async def list_recommendation_notes(recommendation_id: str):
    """List notes attached to a recommendation, most-recent first."""
    try:
        _core_get_payload("recommendations", recommendation_id)
        return _core_notes_for_recommendation(recommendation_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"bluearch-core recommendation notes unavailable: {exc}"
        ) from exc


@router.post(
    "/{recommendation_id}/notes",
    response_model=RecommendationNoteResponse,
    status_code=201,
)
async def create_recommendation_note(
    recommendation_id: str,
    body: CreateRecommendationNoteRequest,
    current_user=Depends(get_current_user),
):
    """Add a note to a recommendation."""
    try:
        _core_get_payload("recommendations", recommendation_id)
        author = body.author
        if not author and current_user is not None:
            author = current_user.email or current_user.sub
        record = request_core(
            "POST",
            "/api/v1/storage/bluearch/recommendation-notes",
            service_token=True,
            json={
                "payload": {
                    "recommendation_id": recommendation_id,
                    "body": body.body.strip(),
                    "author": author,
                }
            },
        )
        return record["payload"]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"bluearch-core recommendation note create unavailable: {exc}"
        ) from exc


@router.patch(
    "/notes/{note_id}",
    response_model=RecommendationNoteResponse,
)
async def update_recommendation_note(
    note_id: str,
    body: UpdateRecommendationNoteRequest,
    _current_user=Depends(get_current_user),
):
    """Edit an existing note body."""
    try:
        current = _core_get_payload("recommendation-notes", note_id)
        current["body"] = body.body.strip()
        record = request_core(
            "PUT",
            f"/api/v1/storage/bluearch/recommendation-notes/{note_id}",
            service_token=True,
            json={"payload": current},
        )
        return record["payload"]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"bluearch-core recommendation note update unavailable: {exc}"
        ) from exc


@router.delete(
    "/notes/{note_id}",
    status_code=204,
)
async def delete_recommendation_note(
    note_id: str,
    _current_user=Depends(get_current_user),
):
    """Delete a note."""
    try:
        _core_get_payload("recommendation-notes", note_id)
        request_core(
            "DELETE",
            f"/api/v1/storage/bluearch/recommendation-notes/{note_id}",
            service_token=True,
        )
        return None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"bluearch-core recommendation note delete unavailable: {exc}"
        ) from exc


def _core_recommendation_payloads(limit: int = 5000, filters: list[tuple[str, str]] | None = None) -> list[dict]:
    params: list[tuple[str, str | int]] = [("limit", limit), ("order_by", "last_updated"), ("descending", "true")]
    for field, value in filters or []:
        params.append(("filter", f"{field}={value}"))
    query = urlencode(params)
    records = request_core(
        "GET",
        f"/api/v1/storage/bluearch/recommendations?{query}",
        service_token=True,
        timeout=10.0,
    )
    return [_normalize_payload(record["payload"]) for record in records]


def _core_note_payloads(limit: int = 5000, recommendation_id: str | None = None) -> list[dict]:
    params: list[tuple[str, str | int]] = [("limit", limit), ("order_by", "created_at"), ("descending", "true")]
    if recommendation_id:
        params.append(("filter", f"recommendation_id={recommendation_id}"))
    query = urlencode(params)
    records = request_core(
        "GET",
        f"/api/v1/storage/bluearch/recommendation-notes?{query}",
        service_token=True,
        timeout=10.0,
    )
    return [_normalize_payload(record["payload"]) for record in records]


def _core_get_payload(collection: str, record_key: str) -> dict:
    try:
        record = request_core(
            "GET",
            f"/api/v1/storage/bluearch/{collection}/{record_key}",
            service_token=True,
            timeout=10.0,
        )
    except Exception as exc:
        if "404" in str(exc):
            detail = "Recommendation not found" if collection == "recommendations" else "Note not found"
            raise HTTPException(status_code=404, detail=detail) from exc
        raise
    return _normalize_payload(record["payload"])


def _core_list_recommendations(
    *,
    recommendation_type: str | None,
    account_id: str | None,
    region: str | None,
    page: int,
    page_size: int,
) -> PaginatedResponse:
    notes_by_rec: dict[str, list[dict]] = {}
    for note in _core_note_payloads():
        notes_by_rec.setdefault(note.get("recommendation_id"), []).append(note)
    for notes in notes_by_rec.values():
        notes.sort(key=lambda item: item.get("created_at") or "", reverse=True)

    filters = []
    if recommendation_type:
        filters.append(("recommendation_type", recommendation_type))
    if account_id:
        filters.append(("account_id", account_id))
    if region:
        filters.append(("region_name", region))

    records = []
    for rec in _core_recommendation_payloads(filters=filters):
        rec["notes"] = notes_by_rec.get(rec.get("id"), [])
        records.append(_serialize_core_rec(rec))

    records.sort(key=lambda item: item.get("last_updated") or "", reverse=True)
    total = len(records)
    start = (page - 1) * page_size
    return PaginatedResponse(items=records[start : start + page_size], total=total, page=page, page_size=page_size)


def _core_notes_for_recommendation(recommendation_id: str) -> list[dict]:
    notes = _core_note_payloads(recommendation_id=recommendation_id)
    notes.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return notes


def _serialize_core_rec(rec: dict) -> dict:
    attrs = rec.get("attributes")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": rec.get("id"),
        "unique_id": rec.get("unique_id"),
        "recommendation_type": rec.get("recommendation_type"),
        "region_name": rec.get("region_name"),
        "account_id": rec.get("account_id"),
        "account_name": rec.get("account_name"),
        "last_updated": rec.get("last_updated"),
        "attributes": attrs,
        "resource_id": rec.get("resource_id"),
        "notes": rec.get("notes") or [],
    }


def _build_recommendation_summary(records: list[dict]) -> RecommendationSummaryResponse:
    by_type: dict[str, int] = {}
    by_account: dict[tuple[str, str], int] = {}
    by_region: dict[str, int] = {}
    for rec in records:
        rec_type = rec.get("recommendation_type")
        if rec_type:
            by_type[rec_type] = by_type.get(rec_type, 0) + 1
        account = rec.get("account_id")
        if account:
            key = (account, rec.get("account_name") or account)
            by_account[key] = by_account.get(key, 0) + 1
        region = rec.get("region_name")
        if region:
            by_region[region] = by_region.get(region, 0) + 1
    return RecommendationSummaryResponse(
        total=len(records),
        by_type=[RecommendationTypeCount(recommendation_type=key, count=value) for key, value in by_type.items()],
        by_account=[
            {"account_id": key[0], "account_name": key[1], "count": value} for key, value in by_account.items()
        ],
        by_region=[{"region": key, "count": value} for key, value in by_region.items()],
    )


def _normalize_payload(payload: dict) -> dict:
    normalized = dict(payload or {})
    attrs = normalized.get("attributes")
    if isinstance(attrs, str):
        try:
            normalized["attributes"] = json.loads(attrs)
        except (json.JSONDecodeError, TypeError):
            pass
    return normalized


def _track_recommendation_list(
    current_user,
    items,
    total: int,
    page: int,
    page_size: int,
    recommendation_type: str | None,
    account_id: str | None,
    region: str | None,
) -> None:
    try:
        track_event(
            "web.recommendations.list",
            properties={
                "user_sub": getattr(current_user, "sub", None),
                "count": len(items),
                "total": total,
                "page": page,
                "page_size": page_size,
                "recommendation_type": recommendation_type,
                "account_id": account_id,
                "region": region,
            },
        )
    except Exception:
        pass
