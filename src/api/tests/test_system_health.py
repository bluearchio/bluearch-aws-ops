import asyncio

from web.routers import system


def test_public_health_contract_reports_service_and_core_readiness(monkeypatch):
    monkeypatch.setattr(
        system,
        "request_core",
        lambda *args, **kwargs: {"status": "ok", "db_ready": True},
    )

    payload = asyncio.run(system.health_check_alias())

    assert payload["service"] == "bluearch-aws-ops"
    assert payload["status"] == "healthy"
    assert payload["database"] == {"connected": True, "source": "bluearch-core"}


def test_public_health_contract_is_unhealthy_when_core_is_unreachable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("core unavailable")

    monkeypatch.setattr(system, "request_core", unavailable)

    payload = asyncio.run(system.health_check_alias())

    assert payload["service"] == "bluearch-aws-ops"
    assert payload["status"] == "unhealthy"
    assert payload["database"]["connected"] is False
    assert "core unavailable" in payload["database"]["error"]
