import httpx
import pytest

from smartstudio_mcp.geocoding import NominatimGeocoder
from smartstudio_mcp.models import DomainError, PlaceInput

pytestmark = pytest.mark.anyio


def provider(settings, handler):
    settings.geocoder_url = "https://geocoder.example/search"
    return NominatimGeocoder(settings, httpx.MockTransport(handler))


async def test_provider_sends_only_place(settings):
    def response(request):
        assert set(request.url.params) == {
            "city",
            "country",
            "format",
            "addressdetails",
            "limit",
            "dedupe",
        }
        assert "SmartStudio" in request.headers["user-agent"]
        return httpx.Response(
            200,
            json=[
                {
                    "lat": "41.1579",
                    "lon": "-8.6291",
                    "address": {"city": "Porto", "country": "Portugal"},
                }
            ],
        )

    candidates = await provider(settings, response).resolve(
        PlaceInput(city="Porto", country="Portugal")
    )
    assert len(candidates) == 1 and candidates[0].city == "Porto"
    assert candidates[0].confidence == "provider_unscored"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(429),
        httpx.Response(200, json={"invalid": True}),
        httpx.Response(200, json=[{"lat": "bad"}]),
        httpx.Response(200, content=b"x" * 131073),
    ],
)
async def test_provider_failures(settings, response):
    with pytest.raises(DomainError) as error:
        await provider(settings, lambda _: response).resolve(
            PlaceInput(city="Porto", country="Portugal")
        )
    assert error.value.code == "GEOCODER_FAILURE"


async def test_provider_timeout(settings):
    def timeout(_):
        raise httpx.ReadTimeout("sensitive query")

    with pytest.raises(DomainError):
        await provider(settings, timeout).resolve(PlaceInput(city="Porto", country="Portugal"))


async def test_external_provider_not_implicitly_enabled(settings):
    settings.geocoder_url = "https://nominatim.openstreetmap.org/search"
    with pytest.raises(ValueError):
        NominatimGeocoder(settings)
