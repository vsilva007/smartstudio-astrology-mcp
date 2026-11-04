import pytest

from smartstudio_mcp.config import Settings
from smartstudio_mcp.models import Location
from smartstudio_mcp.service import Service

PORTO = {
    "birth_date": "1985-07-02",
    "birth_time": "08:05",
    "city": "Porto",
    "country": "Portugal",
    "latitude": 41.1579,
    "longitude": -8.6291,
    "time_precision": "exact",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        allowed_hosts=["testserver", "127.0.0.1:*"],
        allowed_origins=["https://chatgpt.com"],
        rate_per_minute=500,
        global_rate_per_minute=5000,
        metrics_token="test-metrics",
    )


class StubGeocoder:
    def __init__(self, count=1):
        self.count, self.calls = count, 0

    async def resolve(self, place):
        self.calls += 1
        return [
            Location(
                city=place.city,
                country=place.country,
                latitude=41.1579 + i,
                longitude=-8.6291,
                source="test fixture, not production geocoding",
                confidence="curated",
                ambiguous=self.count > 1,
            )
            for i in range(self.count)
        ]


@pytest.fixture
def service(settings):
    instance = Service(settings, StubGeocoder())
    yield instance
    instance.close()
