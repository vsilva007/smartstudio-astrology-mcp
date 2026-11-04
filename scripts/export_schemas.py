import asyncio
import json
import pathlib
import sys

from smartstudio_mcp.server import create_app


async def main():
    app = create_app()
    try:
        tools = await app.mcp.list_tools()
        value = (
            json.dumps(
                [t.model_dump(by_alias=True, exclude_none=True) for t in tools],
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
        target = pathlib.Path("docs/tool-schemas.json")
        if "--check" in sys.argv:
            if target.read_text() != value:
                raise SystemExit("Tool schemas changed; run scripts/export_schemas.py")
        else:
            target.write_text(value)
    finally:
        app.service.close()


asyncio.run(main())
