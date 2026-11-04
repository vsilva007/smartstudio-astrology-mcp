import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse

from . import __version__
from .config import Settings
from .engine import verify_data
from .models import AspectInput, DomainError, NatalInput, PlaceInput, ReferenceInput, Result
from .security import Guard, configure_logging
from .service import Service


def check_public_release(settings: Settings):
    if settings.environment == "development" or settings.local_test_only:
        return
    if not settings.license_review_approved:
        raise RuntimeError("Public activation blocked: license review must be approved")
    url = urlparse(settings.source_url)
    if url.scheme != "https" or not url.hostname or not settings.source_archive.is_file():
        raise RuntimeError("Public activation requires HTTPS corresponding-source URL and archive")
    if settings.release_revision == "development" or not settings.metrics_token:
        raise RuntimeError("Public activation requires release revision and metrics token")
    if any("*" in value for value in settings.allowed_hosts + settings.allowed_origins):
        raise RuntimeError("Production Host and Origin lists must be explicit")


def create_app(settings: Settings | None = None, geocoder=None):
    settings = settings or Settings()
    check_public_release(settings)
    service = Service(settings, geocoder)

    @asynccontextmanager
    async def lifespan(_):
        try:
            yield {}
        finally:
            service.close()

    mcp = MCPServer(
        "Smart Studio — Carta y Arcano" + (" [DEMO]" if settings.environment == "demo" else ""),
        version=__version__,
        lifespan=lifespan,
        instructions=(
            "Numerical astronomy only. Dates and clock values are literal conventional UT, "
            "never verified birth UTC. Always preserve precision warnings. "
            "AGPL-3.0-only; corresponding source: " + (settings.source_url or "/source")
        ),
        website_url="https://smartstudio.dev/carta-y-arcano",
        log_level="WARNING",
    )

    def annotation(external):
        return ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, openWorldHint=external, idempotentHint=True
        )

    @mcp.tool(annotations=annotation(True), structured_output=True)
    async def resolve_birthplace(request: PlaceInput) -> Result:
        """Resolve city/country to coordinates. May query configured external geocoder. Never select ambiguous places."""
        return await service.run("resolve_birthplace", request)

    @mcp.tool(annotations=annotation(True), structured_output=True)
    async def calculate_natal_chart(request: NatalInput) -> Result:
        """Calculate literal-time tropical chart. Supply confirmed coordinates to avoid external geocoding. No UTC/DST conversion; exact clock does not mean verified instant."""
        return await service.run("calculate_natal_chart", request)

    @mcp.tool(annotations=annotation(False), structured_output=True)
    async def calculate_transits(request: ReferenceInput) -> Result:
        """Planet positions and mutual aspects at a literal conventional UT reference, not natal-to-transit synastry."""
        return await service.run("calculate_transits", request)

    @mcp.tool(annotations=annotation(False), structured_output=True)
    async def calculate_aspects(request: AspectInput) -> Result:
        """Deterministic major aspects from supplied 0 <= longitudes < 360. Default orbs 8/4/6/6/8 degrees."""
        return await service.run("calculate_aspects", request)

    @mcp.tool(annotations=annotation(False), structured_output=True)
    async def get_ephemeris(request: ReferenceInput) -> Result:
        """Swiss planetary positions with pinned data provenance; literal conventional UT, not verified UTC."""
        return await service.run("get_ephemeris", request)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def health(_):
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "revision": settings.release_revision,
                "environment": settings.environment,
                "demo": settings.environment == "demo",
                "public_origin": settings.public_origin,
                "local_test_only": settings.local_test_only,
            }
        )

    @mcp.custom_route("/readyz", methods=["GET"])
    async def ready(_):
        try:
            verify_data(settings)
        except DomainError:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return JSONResponse({"status": "ready", "ephemeris": service.engine.source})

    @mcp.custom_route("/.well-known/openai-apps-challenge", methods=["GET"])
    async def challenge(_):
        if not settings.openai_challenge_token:
            return PlainTextResponse("", status_code=404)
        return PlainTextResponse(settings.openai_challenge_token)

    @mcp.custom_route("/source", methods=["GET"])
    async def source(_):
        return JSONResponse(
            {
                "license": "AGPL-3.0-only",
                "revision": settings.release_revision,
                "source_url": settings.source_url or None,
                "download": "/source.tar.gz" if settings.source_archive.is_file() else None,
                "notice": "/notice",
                "license_url": "/license",
                "public_release_ready": settings.environment in {"production", "demo"}
                and not settings.local_test_only,
            }
        )

    @mcp.custom_route("/source.tar.gz", methods=["GET"])
    async def archive(_):
        if not settings.source_archive.is_file():
            return PlainTextResponse("Source archive not prepared", status_code=503)
        return FileResponse(
            settings.source_archive, media_type="application/gzip", filename="source.tar.gz"
        )

    @mcp.custom_route("/license", methods=["GET"])
    async def license_text(_):
        return PlainTextResponse(Path("LICENSE").read_text())

    @mcp.custom_route("/notice", methods=["GET"])
    async def notice(_):
        return PlainTextResponse(
            Path("NOTICE").read_text()
            + "\n"
            + Path("legal/SWISSEPH-LICENSE.txt").read_text()
            + "\n"
            + Path("legal/THIRD-PARTY.md").read_text()
        )

    @mcp.custom_route("/privacy", methods=["GET"])
    async def privacy(_):
        return PlainTextResponse(Path("docs/PRIVACY.md").read_text())

    @mcp.custom_route("/metrics", methods=["GET"])
    async def metrics(request):
        expected = "Bearer " + settings.metrics_token
        if not settings.metrics_token or not hmac.compare_digest(
            request.headers.get("authorization", ""), expected
        ):
            return PlainTextResponse("Unauthorized", status_code=401)
        lines = [
            "# TYPE carta_http_requests_total counter",
            "# TYPE carta_http_duration_seconds_sum counter",
        ]
        for (route, status), count in sorted(guard.counts.items()):
            lines.append(f'carta_http_requests_total{{route="{route}",status="{status}"}} {count}')
        for route, seconds in sorted(guard.seconds.items()):
            lines.append(f'carta_http_duration_seconds_sum{{route="{route}"}} {seconds}')
        lines.append("# TYPE carta_tool_results_total counter")
        for (tool, outcome), count in sorted(service.tool_counts.items()):
            lines.append(f'carta_tool_results_total{{tool="{tool}",outcome="{outcome}"}} {count}')
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.allowed_origins,
    )
    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=settings.max_body_bytes,
        transport_security=security,
    )
    guard = Guard(app, settings, security)
    guard.mcp, guard.service = mcp, service
    configure_logging()
    return guard
