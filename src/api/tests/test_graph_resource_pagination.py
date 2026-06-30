"""Graph router resource pagination tests."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from web.routers import graph


def test_core_all_resources_paginates_with_core_limit(monkeypatch):
    calls: list[dict[str, int]] = []

    def fake_request_core(method: str, path: str, **_kwargs):
        query = parse_qs(urlparse(path).query)
        limit = int(query["limit"][0])
        offset = int(query["offset"][0])
        calls.append({"limit": limit, "offset": offset})
        assert limit <= graph.CORE_RESOURCE_PAGE_SIZE
        if offset == 0:
            return {"total": 1250, "items": [{"resource_arn": f"arn:first:{idx}"} for idx in range(1000)]}
        if offset == 1000:
            return {"total": 1250, "items": [{"resource_arn": f"arn:second:{idx}"} for idx in range(250)]}
        return {"total": 1250, "items": []}

    monkeypatch.setattr(graph, "request_core", fake_request_core)

    payload = graph._core_all_resources_payload(max_items=5000)

    assert len(payload["items"]) == 1250
    assert payload["total"] == 1250
    assert calls == [{"limit": 1000, "offset": 0}, {"limit": 1000, "offset": 1000}]
