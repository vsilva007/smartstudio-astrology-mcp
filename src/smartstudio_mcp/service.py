import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import swisseph as swe

from . import aspects
from .config import Settings
from .engine import Engine, julian_day
from .geocoding import Geocoder, create_geocoder
from .models import (
    AspectInput,
    DomainError,
    Issue,
    Location,
    NatalInput,
    PlaceInput,
    ReferenceInput,
    Result,
)

TEMPORAL_WARNING = Issue(
    code="UNVERIFIED_TIME_REFERENCE",
    message=(
        "Literal supplied date and clock used as conventional UT; no civil-to-UTC, DST or longitude "
        "correction. Results are not verified astronomical positions for the real birth instant."
    ),
)


class Service:
    def __init__(self, settings: Settings, geocoder: Geocoder | None = None):
        self.settings = settings
        self.engine = Engine(settings)
        self.geocoder = geocoder or create_geocoder(settings)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swisseph")
        self.active = 0
        self.tool_counts: dict[tuple[str, str], int] = {}

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def base(self, request) -> Result:
        return Result(
            input=request.model_dump(exclude_unset=True),
            engine_version=swe.version,
            zodiac=getattr(request, "zodiac", None),
            house_system=getattr(request, "house_system", None),
            source_url=self.settings.source_url or "/source",
        )

    async def run(self, operation: str, request) -> Result:
        result = self.base(request)
        if self.settings.environment == "demo":
            result.warnings.append(
                Issue(code="DEMO", message="DEMO installation; external integrations disabled.")
            )
        if operation in {"resolve_birthplace", "calculate_aspects"}:
            result.time_reference = "not_applicable"
            result.precision_status = "not_applicable"
        else:
            result.warnings.append(TEMPORAL_WARNING)
        try:
            if self.active >= self.settings.max_concurrent:
                raise DomainError("SERVICE_BUSY", "Service at capacity; retry later.")
            self.active += 1
            try:
                async with asyncio.timeout(self.settings.request_timeout - 0.25):
                    await getattr(self, operation)(request, result)
            finally:
                self.active -= 1
        except TimeoutError:
            result.errors.append(
                Issue(code="CALCULATION_TIMEOUT", message="Calculation timed out.")
            )
        except DomainError as exc:
            result.errors.append(Issue(code=exc.code, message=exc.message))
        except Exception:
            logging.getLogger(__name__).error(
                "Unexpected tool failure", extra={"event": "tool_failure"}
            )
            result.errors.append(Issue(code="INTERNAL_ERROR", message="Internal service failure."))
        if result.errors:
            result.success = False
            result.positions, result.houses, result.angles, result.aspects = [], [], {}, []
            result.julian_day, result.effective_clock = None, None
        key = (operation, "success" if result.success else result.errors[0].code)
        self.tool_counts[key] = self.tool_counts.get(key, 0) + 1
        return result

    async def resolve_birthplace(self, request: PlaceInput, result: Result):
        candidates = await self.geocoder.resolve(request)
        result.candidates = candidates
        if not candidates:
            raise DomainError("LOCATION_NOT_FOUND", "No matching locality was found.")
        if len(candidates) != 1:
            result.ambiguous = True
            raise DomainError(
                "AMBIGUOUS_LOCATION",
                "Multiple localities match; specify region or confirmed coordinates.",
            )
        result.resolved_location = candidates[0]

    async def calculate_natal_chart(self, request: NatalInput, result: Result):
        if request.require_verified_instant:
            raise DomainError(
                "VERIFIED_INSTANT_UNAVAILABLE",
                "This service only supports unverified literal clock references.",
            )
        if request.latitude is not None:
            result.resolved_location = Location(
                city=request.city,
                country=request.country,
                region=request.region,
                latitude=request.latitude,
                longitude=request.longitude,
                source="user_supplied",
                confidence="user_supplied",
            )
        else:
            await self.resolve_birthplace(
                PlaceInput(city=request.city, country=request.country, region=request.region),
                result,
            )
        clock = request.birth_time or "12:00"
        unknown = request.time_precision == "unknown"
        result.julian_day = julian_day(request.birth_date, clock)
        result.effective_clock = clock
        if unknown:
            result.time_reference = "noon_convention_used_as_ut"
            result.warnings.append(
                Issue(
                    code="UNKNOWN_BIRTH_TIME",
                    message=(
                        "12:00 is a representative convention, not supplied birth time. No houses, angles "
                        "or natal aspects; sampled signs and longitudes describe day variation."
                    ),
                )
            )
        elif request.time_precision == "approximate":
            result.warnings.append(
                Issue(
                    code="APPROXIMATE_BIRTH_TIME",
                    message=(
                        "Supplied clock is approximate; no error margin was supplied. Angles and houses "
                        "are illustrative and no stability or exact uncertainty is claimed."
                    ),
                )
            )
        (
            result.positions,
            result.houses,
            result.angles,
        ) = await asyncio.get_running_loop().run_in_executor(
            self.executor,
            partial(
                self.engine.calculate,
                result.julian_day,
                request.node_type,
                None if unknown else result.resolved_location,
                None if unknown else request.house_system,
                unknown,
            ),
        )
        result.ephemeris_source = self.engine.source
        if not unknown:
            result.aspects = aspects.calculate({p.body: p.longitude for p in result.positions})
            result.warnings.append(
                Issue(
                    code="HOUSE_ASSIGNMENT_CONVENTION",
                    message=(
                        "Planet houses use zodiacal longitude cusp intervals, ignoring ecliptic latitude."
                    ),
                )
            )
            if request.time_precision == "approximate":
                for p in result.positions + list(result.angles.values()):
                    p.uncertainty = "Approximate clock; temporal uncertainty unquantified."

    async def get_ephemeris(self, request: ReferenceInput, result: Result):
        result.julian_day = julian_day(request.reference_date, request.reference_time)
        result.effective_clock = request.reference_time
        result.positions, _, _ = await asyncio.get_running_loop().run_in_executor(
            self.executor, partial(self.engine.calculate, result.julian_day, request.node_type)
        )
        result.ephemeris_source = self.engine.source

    async def calculate_transits(self, request: ReferenceInput, result: Result):
        await self.get_ephemeris(request, result)
        result.aspects = aspects.calculate({p.body: p.longitude for p in result.positions})

    async def calculate_aspects(self, request: AspectInput, result: Result):
        result.engine = "Smart Studio angular separation"
        result.engine_version = "0.1.0"
        result.aspects = aspects.calculate(request.longitudes, request.orbs)
