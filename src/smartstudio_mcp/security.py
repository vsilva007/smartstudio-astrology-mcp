import asyncio
import json
import logging
import time
from collections import Counter, OrderedDict

from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Settings

ROUTES = {
    "/mcp",
    "/healthz",
    "/readyz",
    "/source",
    "/source.tar.gz",
    "/license",
    "/notice",
    "/privacy",
    "/metrics",
    "/.well-known/openai-apps-challenge",
}


class TechnicalFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "timestamp": self.formatTime(record),
                "level": record.levelname,
                "event": getattr(record, "event", "library_event"),
                "route": getattr(record, "route", None),
                "status": getattr(record, "status", None),
                "duration_ms": getattr(record, "duration_ms", None),
            }
        )


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(TechnicalFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ("mcp", "httpx", "httpcore", "httpx2", "httpcore2", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.WARNING)


class Guard:
    def __init__(self, app, settings: Settings, security: TransportSecuritySettings):
        self.app, self.settings = app, settings
        self.transport = TransportSecurityMiddleware(security)
        self.clients = OrderedDict()
        self.global_bucket = (float(settings.global_rate_per_minute), time.monotonic())
        self.active = 0
        self.counts = Counter()
        self.seconds = Counter()

    @staticmethod
    def consume(bucket, limit, now):
        tokens, last = bucket
        tokens = min(float(limit), tokens + (now - last) * limit / 60)
        return tokens >= 1, (max(0.0, tokens - 1), now)

    def allow(self, address):
        now = time.monotonic()
        allowed, self.global_bucket = self.consume(
            self.global_bucket, self.settings.global_rate_per_minute, now
        )
        if not allowed:
            return False
        bucket = self.clients.pop(address, (float(self.settings.rate_per_minute), now))
        allowed, bucket = self.consume(bucket, self.settings.rate_per_minute, now)
        self.clients[address] = bucket
        while len(self.clients) > 4096:
            self.clients.popitem(last=False)
        return allowed

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        route = scope["path"] if scope["path"] in ROUTES else "other"
        status, response_started = 500, False

        async def tracked_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
                message["headers"].append(
                    (b"x-carta-environment", self.settings.environment.encode())
                )
                if self.settings.environment == "demo":
                    message["headers"].append((b"x-robots-tag", b"noindex, nofollow, noarchive"))
                message["headers"] += [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        async def reject(code, message, headers=None):
            await JSONResponse({"error": message}, status_code=code, headers=headers)(
                scope, receive, tracked_send
            )

        try:
            rejection = await self.transport.validate_request(Request(scope))
            if rejection:
                return await rejection(scope, receive, tracked_send)
            address = (scope.get("client") or ("unknown", 0))[0]
            if not self.allow(address):
                return await reject(429, "rate_limit_exceeded", {"Retry-After": "60"})
            if self.active >= self.settings.max_concurrent:
                return await reject(503, "service_busy", {"Retry-After": "1"})
            self.active += 1
            try:
                async with asyncio.timeout(self.settings.request_timeout):
                    await self.app(scope, receive, tracked_send)
            finally:
                self.active -= 1
        except TimeoutError:
            if not response_started:
                await reject(504, "request_timeout")
        except Exception:
            if not response_started:
                await reject(500, "internal_error")
        finally:
            elapsed = time.monotonic() - started
            self.counts[(route, status)] += 1
            self.seconds[route] += elapsed
            logging.getLogger(__name__).info(
                "request",
                extra={
                    "event": "http_request",
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                },
            )
