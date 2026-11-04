import asyncio
import time
from typing import Protocol
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from .config import Settings
from .models import DomainError, Location, PlaceInput


class Geocoder(Protocol):
    async def resolve(self, place: PlaceInput) -> list[Location]: ...


class DisabledGeocoder:
    async def resolve(self, place: PlaceInput) -> list[Location]:
        raise DomainError("GEOCODER_NOT_CONFIGURED", "Provide coordinates or configure a geocoder.")


class NominatimGeocoder:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        url = urlparse(settings.geocoder_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Geocoder must have an operator-configured HTTPS URL")
        if url.hostname == "nominatim.openstreetmap.org":
            raise ValueError(
                "Configure an authorized or self-hosted Nominatim instance; public OSMF API is not enabled"
            )
        self.settings, self.transport = settings, transport
        self.lock = asyncio.Lock()
        self.last_request = 0.0

    async def resolve(self, place: PlaceInput) -> list[Location]:
        params = {
            "city": place.city,
            "country": place.country,
            "format": "jsonv2",
            "addressdetails": "1",
            "limit": "10",
            "dedupe": "1",
        }
        if place.region:
            params["state"] = place.region
        async with self.lock:
            delay = self.settings.geocoder_min_interval - (time.monotonic() - self.last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last_request = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=5, follow_redirects=False, trust_env=False, transport=self.transport
                ) as client:
                    async with client.stream(
                        "GET",
                        self.settings.geocoder_url,
                        params=params,
                        headers={"User-Agent": self.settings.geocoder_user_agent},
                    ) as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 131072:
                                raise DomainError(
                                    "GEOCODER_FAILURE", "Geocoder response too large."
                                )
                        import json

                        rows = json.loads(body)
                if not isinstance(rows, list) or len(rows) > 10:
                    raise ValueError("Unexpected response")
                candidates = []
                seen = set()
                for row in rows:
                    address = row["address"]
                    city = next(
                        (
                            address[k]
                            for k in ("city", "town", "village", "municipality", "hamlet")
                            if address.get(k)
                        ),
                        None,
                    )
                    if not city:
                        continue
                    location = Location(
                        city=city,
                        country=address["country"],
                        region=address.get("state"),
                        latitude=float(row["lat"]),
                        longitude=float(row["lon"]),
                        source="Nominatim / © OpenStreetMap contributors (ODbL)",
                        confidence="provider_unscored",
                    )
                    key = (location.city, location.country, location.latitude, location.longitude)
                    if key not in seen:
                        candidates.append(location)
                        seen.add(key)
                for location in candidates:
                    location.ambiguous = len(candidates) > 1
                return candidates
            except (httpx.HTTPError, ValueError, KeyError, TypeError, ValidationError) as exc:
                raise DomainError(
                    "GEOCODER_FAILURE", "Geocoding unavailable; provide coordinates or retry later."
                ) from exc


def create_geocoder(settings: Settings) -> Geocoder:
    return NominatimGeocoder(settings) if settings.geocoder == "nominatim" else DisabledGeocoder()
