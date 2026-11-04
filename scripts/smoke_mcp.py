import argparse
import asyncio
import json

from mcp import Client


async def main(url):
    async with Client(url) as client:
        listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        assert names == {
            "resolve_birthplace",
            "calculate_natal_chart",
            "calculate_transits",
            "calculate_aspects",
            "get_ephemeris",
        }
        result = await client.call_tool(
            "calculate_natal_chart",
            {
                "request": {
                    "birth_date": "1985-07-02",
                    "birth_time": "08:05",
                    "time_precision": "exact",
                    "city": "Porto",
                    "country": "Portugal",
                    "latitude": 41.1579,
                    "longitude": -8.6291,
                }
            },
        )
        chart = result.structured_content
        assert chart["success"] and chart["effective_clock"] == "08:05"
        assert chart["precision_status"] == "civil_time_not_utc_verified"
        print(
            json.dumps(
                {
                    "tools": sorted(names),
                    "engine_version": chart["engine_version"],
                    "calculation_mode": chart["calculation_mode"],
                    "success": True,
                }
            )
        )


parser = argparse.ArgumentParser()
parser.add_argument("url", nargs="?", default="http://127.0.0.1:8000/mcp")
asyncio.run(main(parser.parse_args().url))
