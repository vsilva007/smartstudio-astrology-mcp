import asyncio
import json
import logging

import pytest
from conftest import PORTO, StubGeocoder
from starlette.testclient import TestClient

from smartstudio_mcp.models import DomainError
from smartstudio_mcp.security import TechnicalFormatter
from smartstudio_mcp.server import create_app

HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}


def call(client, name, request):
    return client.post(
        "/mcp",
        headers=HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": {"request": request}},
        },
    )


def test_mcp_initialize_discover_and_all_tools(settings):
    with TestClient(create_app(settings, StubGeocoder())) as client:
        init = client.post(
            "/mcp",
            headers=HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert init.status_code == 200, init.text
        assert "result" in init.json()
        discovery = client.post(
            "/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        tools = {t["name"]: t for t in discovery.json()["result"]["tools"]}
        assert set(tools) == {
            "resolve_birthplace",
            "calculate_natal_chart",
            "calculate_transits",
            "calculate_aspects",
            "get_ephemeris",
        }
        requests = {
            "resolve_birthplace": {"city": "Porto", "country": "Portugal"},
            "calculate_natal_chart": PORTO,
            "calculate_transits": {"reference_date": "2026-11-03", "reference_time": "10:00"},
            "get_ephemeris": {"reference_date": "2026-11-03", "reference_time": "10:00"},
            "calculate_aspects": {"longitudes": {"Sun": 0.0, "Moon": 90.0}},
        }
        from jsonschema import validate

        for name, request in requests.items():
            tool = tools[name]
            validate({"request": request}, tool["inputSchema"])
            assert tool["annotations"]["readOnlyHint"] is True
            assert tool["annotations"]["destructiveHint"] is False
            assert tool["annotations"]["openWorldHint"] == (
                name in {"resolve_birthplace", "calculate_natal_chart"}
            )
            response = call(client, name, request)
            assert response.status_code == 200, response.text
            result = response.json()["result"]
            assert not result.get("isError"), result
            validate(result["structuredContent"], tool["outputSchema"])
            assert result["structuredContent"]["success"], result


def test_host_origin_body_and_validation(settings):
    with TestClient(create_app(settings, StubGeocoder())) as client:
        assert client.get("/healthz", headers={"Host": "evil.example"}).status_code == 421
        assert client.get("/healthz", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/healthz", headers={"Origin": "https://chatgpt.com"}).status_code == 200
        assert client.post("/mcp", content=b"x" * 32769, headers=HEADERS).status_code == 413

        def chunks():
            yield b"x" * 20000
            yield b"y" * 20000

        assert client.post("/mcp", content=chunks(), headers=HEADERS).status_code == 413
        response = call(client, "calculate_natal_chart", PORTO | {"birth_date": "1985-02-30"})
        payload = response.json()
        assert "error" in payload or payload["result"].get("isError")


def test_rate_limit_cannot_be_spoofed(settings):
    settings.rate_per_minute = 2
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200
        response = client.get("/healthz", headers={"X-Forwarded-For": "8.8.8.8"})
        assert response.status_code == 429 and response.headers["Retry-After"] == "60"


def test_challenge_exact_metrics_and_health(settings):
    token = "exact-portal-token-for-test"
    settings.openai_challenge_token = token
    with TestClient(create_app(settings)) as client:
        assert client.get("/.well-known/openai-apps-challenge").content == token.encode()
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.get("/metrics").status_code == 401
        response = client.get("/metrics", headers={"Authorization": "Bearer test-metrics"})
        assert response.status_code == 200 and "carta_http_requests_total" in response.text
        assert client.get("/source").json()["public_release_ready"] is False


def test_missing_challenge_is_not_verified(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/.well-known/openai-apps-challenge").status_code == 404


def test_license_is_agpl_and_demo_is_identified(settings):
    settings.environment = "demo"
    settings.public_origin = "http://127.0.0.1:4200"
    settings.local_test_only = True
    with TestClient(create_app(settings)) as client:
        assert "GNU AFFERO GENERAL PUBLIC LICENSE" in client.get("/license").text
        health = client.get("/healthz")
        assert health.json()["demo"] is True
        assert health.headers["X-Carta-Environment"] == "demo"
        assert "noindex" in health.headers["X-Robots-Tag"]
        result = call(client, "calculate_aspects", {"longitudes": {"Sun": 0.0, "Moon": 90.0}})
        assert any(
            w["code"] == "DEMO" for w in result.json()["result"]["structuredContent"]["warnings"]
        )
        assert client.get("/source").json()["public_release_ready"] is False


def test_demo_public_activation_and_local_bypass_constraints(settings):
    from pydantic import ValidationError

    from smartstudio_mcp.config import Settings

    settings.environment = "demo"
    with pytest.raises(RuntimeError, match="license"):
        create_app(settings)
    with pytest.raises(ValidationError, match="loopback"):
        Settings(_env_file=None, local_test_only=True, public_origin="https://demo.example.org")
    with pytest.raises(ValidationError, match="external"):
        Settings(_env_file=None, environment="demo", geocoder="nominatim")


def test_public_activation_is_blocked(settings):
    settings.environment = "production"
    with pytest.raises(RuntimeError, match="license"):
        create_app(settings)


def test_missing_ephemerides_fail_startup(settings, tmp_path):
    settings.ephemeris_dir = tmp_path
    with pytest.raises(DomainError, match="EPHEMERIS_DATA_UNAVAILABLE"):
        create_app(settings)


def test_logging_never_serializes_exception_or_message():
    record = logging.LogRecord(
        "mcp", logging.ERROR, "test", 1, "birth date 1985-07-02 private-token", (), None
    )
    record.route = "/mcp"
    data = TechnicalFormatter().format(record)
    assert "1985" not in data and "private-token" not in data
    assert json.loads(data)["route"] == "/mcp"


def test_tool_timeout_and_capacity(settings):
    class SlowGeocoder:
        async def resolve(self, _):
            await asyncio.sleep(2)

    settings.request_timeout = 1.0
    settings.max_concurrent = 1
    with TestClient(create_app(settings, SlowGeocoder())) as client:
        response = call(client, "resolve_birthplace", {"city": "Porto", "country": "Portugal"})
        assert (
            response.json()["result"]["structuredContent"]["errors"][0]["code"]
            == "CALCULATION_TIMEOUT"
        )
