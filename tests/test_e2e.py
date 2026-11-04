import asyncio
import socket
import threading
import time

import uvicorn
from conftest import PORTO, StubGeocoder
from mcp import Client

from smartstudio_mcp.server import create_app


def test_official_sdk_real_streamable_http(settings):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, StubGeocoder()),
            log_level="error",
            access_log=False,
            proxy_headers=False,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started

        async def exercise():
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                tools = await client.list_tools()
                assert len(tools.tools) == 5
                result = await client.call_tool("calculate_natal_chart", {"request": PORTO})
                assert result.structured_content["success"]
                assert result.structured_content["effective_clock"] == "08:05"

        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
    assert not thread.is_alive()
