"""Functional HTTP/MCP release checks; requires only Python's standard library."""

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

TOOLS = {
    "resolve_birthplace",
    "calculate_natal_chart",
    "calculate_transits",
    "calculate_aspects",
    "get_ephemeris",
}
FIELDS = {
    "success",
    "calculation_mode",
    "input",
    "resolved_location",
    "time_reference",
    "precision_status",
    "engine",
    "engine_version",
    "ephemeris_source",
    "zodiac",
    "house_system",
    "positions",
    "houses",
    "angles",
    "aspects",
    "warnings",
    "errors",
}


class CheckError(Exception):
    pass


def check(condition, message):
    if not condition:
        raise CheckError(message)


def verify(base, origin, environment, revision):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    hostname = urlparse(origin).netloc
    counter = 0

    def http(path, payload=None, host=None, origin_header=None):
        headers = {
            "Host": host or hostname,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if origin_header:
            headers["Origin"] = origin_header
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(base + path, headers=headers, data=data)
        try:
            response = opener.open(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read(40 * 1024 * 1024 + 1)
            check(len(body) <= 40 * 1024 * 1024, "HTTP response too large")
            return response.status, response.headers, body

    def rpc(method, params=None):
        nonlocal counter
        counter += 1
        status, _, data = http(
            "/mcp", {"jsonrpc": "2.0", "id": counter, "method": method, "params": params or {}}
        )
        check(status == 200, "MCP HTTP failure")
        value = json.loads(data)
        check("result" in value and "error" not in value, "MCP protocol error")
        return value["result"]

    status, headers, body = http("/healthz")
    health = json.loads(body)
    check(status == 200 and health.get("status") == "ok", "Health response invalid")
    check(
        health.get("environment") == environment and health.get("revision") == revision,
        "Wrong running environment/revision",
    )
    check(health.get("public_origin") == origin, "Wrong public origin")
    check(headers.get("X-Carta-Environment") == environment, "Environment header missing")
    check(
        environment != "demo" or "noindex" in headers.get("X-Robots-Tag", ""), "Demo is indexable"
    )
    check(http("/healthz", host="invalid.example")[0] == 421, "Host protection missing")
    check(
        http("/healthz", origin_header="https://invalid.example")[0] == 403,
        "Origin protection missing",
    )
    check(http("/does-not-exist")[0] == 404, "Unknown routes must return 404")
    check(http("/metrics")[0] == 401, "Metrics must require authentication")
    status, _, body = http("/readyz")
    check(status == 200 and json.loads(body).get("status") == "ready", "Ephemeris readiness failed")
    for path, content in [
        ("/license", b"GNU AFFERO GENERAL PUBLIC LICENSE"),
        ("/notice", b"Swiss Ephemeris"),
        ("/privacy", b"Privacidad"),
    ]:
        status, _, body = http(path)
        check(status == 200 and content in body, f"Legal endpoint failed: {path}")
    status, _, body = http("/source")
    source = json.loads(body)
    check(
        status == 200
        and source.get("revision") == revision
        and source.get("download") == "/source.tar.gz",
        "Wrong corresponding-source offer",
    )
    check(
        source.get("source_url") == origin + "/source.tar.gz",
        "Source URL belongs to another environment",
    )
    status, _, body = http("/source.tar.gz")
    check(
        status == 200 and body.startswith(b"\x1f\x8b") and len(body) > 10000,
        "Source archive unavailable",
    )
    source_hash = hashlib.sha256(body).hexdigest()
    status, _, body = http("/.well-known/openai-apps-challenge")
    token = os.environ.get("VERIFY_CHALLENGE", "")
    check(
        (status == 200 and body == token.encode()) if token else (status == 404 and body == b""),
        "Challenge response is not exact",
    )
    init = rpc(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "smartstudio-deploy", "version": "1"},
        },
    )
    check(
        environment != "demo" or "DEMO" in init["serverInfo"]["name"], "Demo MCP identity missing"
    )
    listing = rpc("tools/list")["tools"]
    check({tool["name"] for tool in listing} == TOOLS, "Unexpected MCP tools")
    for tool in listing:
        annotations = tool.get("annotations", {})
        check(
            annotations.get("readOnlyHint") is True and annotations.get("destructiveHint") is False,
            "Unsafe annotations",
        )
        check(
            annotations.get("openWorldHint")
            == (tool["name"] in {"resolve_birthplace", "calculate_natal_chart"}),
            "Wrong openWorldHint",
        )
        check(
            "request" in tool["inputSchema"].get("properties", {}) and tool.get("outputSchema"),
            "Tool schemas missing",
        )

    def tool(name, request):
        result = rpc("tools/call", {"name": name, "arguments": {"request": request}})
        check(not result.get("isError"), "Tool execution error")
        value = result["structuredContent"]
        check(FIELDS <= value.keys(), "Incomplete structured contract")
        check(value["calculation_mode"] == "literal_no_timezone", "Temporal convention changed")
        check(
            environment != "demo" or any(w["code"] == "DEMO" for w in value["warnings"]),
            "Demo warning missing",
        )
        return value

    birth = {
        "birth_date": "1985-07-02",
        "birth_time": "08:05",
        "city": "Porto",
        "country": "Portugal",
        "latitude": 41.1579,
        "longitude": -8.6291,
        "time_precision": "exact",
    }
    natal = tool("calculate_natal_chart", birth)
    check(
        natal["success"] and natal["input"] == birth and natal["effective_clock"] == "08:05",
        "Literal Porto calculation failed",
    )
    check(
        natal["precision_status"] == "civil_time_not_utc_verified"
        and natal["time_reference"] == "supplied_clock_used_as_ut",
        "Misleading time metadata",
    )
    check(
        len(natal["positions"]) == 12 and len(natal["houses"]) == 12 and len(natal["angles"]) == 2,
        "Incomplete chart",
    )
    check(
        abs(natal["positions"][0]["longitude"] - 100.3844414) < 1e-5,
        "Astronomical regression mismatch",
    )
    reference = {"reference_date": "2000-01-01", "reference_time": "12:00"}
    ephemeris = tool("get_ephemeris", reference)
    transits = tool("calculate_transits", reference)
    check(
        ephemeris["success"]
        and transits["success"]
        and ephemeris["positions"] == transits["positions"],
        "Ephemeris/transit inconsistency",
    )
    check(
        transits["aspects"] and ephemeris["ephemeris_source"].startswith("swiss_files:"),
        "Missing astronomical provenance",
    )
    aspects = tool("calculate_aspects", {"longitudes": {"Sun": 0.0, "Moon": 90.0}})
    check(
        aspects["success"]
        and len(aspects["aspects"]) == 1
        and aspects["aspects"][0]["aspect"] == "square",
        "Aspect calculation failed",
    )
    # Never trigger external geocoding during an unattended deployment check.
    if os.environ.get("VERIFY_GEOCODER", "disabled") == "disabled":
        place = tool("resolve_birthplace", {"city": "Porto", "country": "Portugal"})
        check(
            not place["success"] and place["errors"][0]["code"] == "GEOCODER_NOT_CONFIGURED",
            "Disabled geocoder unexpectedly active",
        )
    unknown = tool(
        "calculate_natal_chart", birth | {"birth_time": None, "time_precision": "unknown"}
    )
    check(
        unknown["success"] and not unknown["houses"] and not unknown["angles"],
        "Unknown birth time generated angles",
    )
    exact = tool("calculate_natal_chart", birth | {"require_verified_instant": True})
    check(not exact["success"] and not exact["positions"], "Verified instant falsely claimed")
    print(
        json.dumps(
            {
                "verified": True,
                "environment": environment,
                "revision": revision,
                "source_sha256": source_hash,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--env", required=True, choices=["production", "demo"])
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    try:
        verify(args.base, args.origin, args.env, args.revision)
    except (CheckError, OSError, ValueError, KeyError) as error:
        raise SystemExit(f"Functional verification failed: {error}") from None
