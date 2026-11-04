import asyncio
import json
import math
from pathlib import Path

import pytest
import swisseph as swe
from conftest import PORTO, StubGeocoder
from pydantic import ValidationError

from smartstudio_mcp.aspects import calculate
from smartstudio_mcp.engine import julian_day
from smartstudio_mcp.models import AspectInput, NatalInput, OrbConfig, PlaceInput, ReferenceInput

pytestmark = pytest.mark.anyio


async def test_porto_literal_and_reference(service):
    request = NatalInput(**PORTO)
    result = await service.run("calculate_natal_chart", request)
    assert result.success, result.errors
    assert result.input == PORTO
    assert result.effective_clock == "08:05"
    assert result.julian_day == pytest.approx(2446248.8368055555, abs=1e-9)
    assert result.calculation_mode == "literal_no_timezone"
    assert result.time_reference == "supplied_clock_used_as_ut"
    assert result.precision_status == "civil_time_not_utc_verified"
    assert service.geocoder.calls == 0
    assert len(result.houses) == 12 and len(result.positions) == 12 and len(result.angles) == 2
    swe.set_ephe_path(str(service.settings.ephemeris_dir.resolve()))
    sun, flags = swe.calc_ut(result.julian_day, swe.SUN, swe.FLG_SWIEPH | swe.FLG_SPEED)
    assert flags & swe.FLG_SWIEPH
    assert result.positions[0].longitude == pytest.approx(sun[0], abs=1e-10)
    cusps, angles = swe.houses_ex(result.julian_day, 41.1579, -8.6291, b"P")
    assert [h.longitude for h in result.houses] == pytest.approx(cusps)
    assert result.angles["Ascendant"].longitude == pytest.approx(angles[0])
    assert all(p.house in range(1, 13) for p in result.positions)
    north, south = result.positions[-2:]
    assert (south.longitude - north.longitude) % 360 == pytest.approx(180)
    assert north.retrograde == south.retrograde


async def test_longitude_does_not_correct_clock(service):
    west, east = await asyncio.gather(
        *[
            service.run("calculate_natal_chart", NatalInput(**(PORTO | {"longitude": value})))
            for value in [-8.6291, 120.0]
        ]
    )
    assert west.julian_day == east.julian_day
    assert [p.longitude for p in west.positions] == [p.longitude for p in east.positions]
    assert west.angles != east.angles


async def test_unknown_time_and_moon_sign_transition(service):
    request = NatalInput(**(PORTO | {"birth_time": None, "time_precision": "unknown"}))
    result = await service.run("calculate_natal_chart", request)
    assert result.success, result.errors
    assert not result.houses and not result.angles and not result.aspects
    assert result.input["birth_time"] is None
    assert result.effective_clock == "12:00"
    assert result.time_reference == "noon_convention_used_as_ut"
    moon = result.positions[1]
    assert len(moon.sampled_longitudes) == 49 and moon.uncertainty
    transition = None
    for day in range(1, 5):
        candidate = NatalInput(
            **(
                PORTO
                | {
                    "birth_date": f"1985-07-{day:02}",
                    "birth_time": None,
                    "time_precision": "unknown",
                }
            )
        )
        data = await service.run("calculate_natal_chart", candidate)
        if len(data.positions[1].possible_signs) > 1:
            transition = data
            break
    assert transition is not None


async def test_approximate_time(service):
    result = await service.run(
        "calculate_natal_chart", NatalInput(**(PORTO | {"time_precision": "approximate"}))
    )
    assert result.success
    assert result.positions[1].uncertainty
    assert "APPROXIMATE_BIRTH_TIME" in {w.code for w in result.warnings}


async def test_ambiguous_place(service):
    service.geocoder = StubGeocoder(2)
    result = await service.run("resolve_birthplace", PlaceInput(city="Springfield", country="US"))
    assert not result.success and result.ambiguous
    assert result.errors[0].code == "AMBIGUOUS_LOCATION"
    assert result.resolved_location is None and len(result.candidates) == 2
    request = {k: v for k, v in PORTO.items() if k not in {"latitude", "longitude"}}
    natal = await service.run("calculate_natal_chart", NatalInput(**request))
    assert not natal.positions


async def test_unique_place(service):
    result = await service.run("resolve_birthplace", PlaceInput(city="Porto", country="Portugal"))
    assert result.success and result.resolved_location.city == "Porto"
    assert result.time_reference == "not_applicable"
    assert "timezone" not in result.model_dump_json().replace("literal_no_timezone", "")


@pytest.mark.parametrize(
    "change",
    [
        {"birth_date": "1985-02-30"},
        {"birth_date": "2399-13-01"},
        {"birth_date": "02/07/1985"},
        {"birth_time": "24:00"},
        {"birth_time": "8:05"},
        {"latitude": 91.0},
        {"longitude": -181.0},
        {"latitude": math.nan},
        {"latitude": "41.2"},
        {"longitude": None},
        {"time_precision": "unknown"},
        {"zodiac": "sidereal"},
        {"house_system": "Koch"},
        {"node_type": "osculating"},
        {"city": " "},
        {"name": "Must not be collected"},
        {"timezone": "Europe/Lisbon"},
    ],
)
async def test_invalid_input(change):
    with pytest.raises(ValidationError):
        NatalInput(**(PORTO | change))


async def test_no_verified_instant_claim(service):
    result = await service.run(
        "calculate_natal_chart", NatalInput(**(PORTO | {"require_verified_instant": True}))
    )
    assert not result.success
    assert result.errors[0].code == "VERIFIED_INSTANT_UNAVAILABLE"
    assert not result.positions and not result.houses


async def test_polar_placidus_requires_explicit_alternative(service):
    data = PORTO | {"latitude": 89.0}
    result = await service.run("calculate_natal_chart", NatalInput(**data))
    assert not result.success and result.errors[0].code == "HOUSE_GEOMETRY_UNDEFINED"
    assert not result.positions and not result.houses
    result = await service.run(
        "calculate_natal_chart", NatalInput(**(data | {"house_system": "WholeSign"}))
    )
    assert result.success and len(result.houses) == 12


async def test_engine_errors_clear_all_values(service, monkeypatch):
    def fail(*args):
        raise swe.Error("private engine details")

    monkeypatch.setattr(swe, "calc_ut", fail)
    result = await service.run("calculate_natal_chart", NatalInput(**PORTO))
    assert not result.success and result.errors[0].code == "ENGINE_ERROR"
    assert not result.positions and result.julian_day is None
    assert "private" not in result.model_dump_json()


async def test_engine_fallback_rejected(service, monkeypatch):
    monkeypatch.setattr(swe, "calc_ut", lambda *args: ((0.0,) * 6, swe.FLG_MOSEPH))
    result = await service.run("calculate_natal_chart", NatalInput(**PORTO))
    assert result.errors[0].code == "EPHEMERIS_FALLBACK_REJECTED"
    assert not result.positions


async def test_aspects_wrap_boundary_and_orbs(service):
    found = calculate({"A": 359.0, "B": 1.0})
    assert len(found) == 1 and found[0].orb == 2
    assert calculate({"A": 0.0, "B": 64.0})[0].aspect == "sextile"
    assert not calculate({"A": 0.0, "B": 64.0001})
    assert calculate({"A": 10.0, "B": 190.0})[0].orb == 0
    assert not calculate({"A": 0.0, "B": 7.0}, OrbConfig(conjunction=6.0))
    a = await service.run("calculate_aspects", AspectInput(longitudes={"A": 90.0, "B": 0.0}))
    b = await service.run("calculate_aspects", AspectInput(longitudes={"B": 0.0, "A": 90.0}))
    assert a.aspects == b.aspects


async def test_transits_and_ephemeris(service):
    reference = ReferenceInput(reference_date="2026-11-03", reference_time="10:00")
    ephe = await service.run("get_ephemeris", reference)
    transits = await service.run("calculate_transits", reference)
    assert ephe.success and transits.success and transits.aspects
    assert ephe.positions == transits.positions and not ephe.aspects
    assert ephe.engine_version == swe.version and ephe.ephemeris_source.startswith("swiss_files:")
    assert ephe.warnings and ephe.time_reference == "supplied_clock_used_as_ut"


async def test_node_type_preserved(service):
    a = await service.run("calculate_natal_chart", NatalInput(**PORTO))
    b = await service.run("calculate_natal_chart", NatalInput(**(PORTO | {"node_type": "true"})))
    assert a.positions[-2].longitude != b.positions[-2].longitude
    assert b.positions[-1].longitude == pytest.approx((b.positions[-2].longitude + 180) % 360)


async def test_concurrent_determinism(service):
    results = await asyncio.gather(
        *[service.run("calculate_natal_chart", NatalInput(**PORTO)) for _ in range(8)]
    )
    assert all(r.success for r in results)
    assert all(r.model_dump() == results[0].model_dump() for r in results)


async def test_julian_gregorian_reference():
    assert julian_day("2000-01-01", "12:00") == 2451545.0


async def test_compiled_c_reference(service):
    fixture = json.loads(Path("tests/fixtures/porto-swetest.json").read_text())
    result = await service.run("calculate_natal_chart", NatalInput(**PORTO))
    assert result.success
    values = fixture["values"]
    for position in result.positions[:-1]:
        name = "mean Node" if position.body == "NorthNode" else position.body
        assert position.longitude == pytest.approx(values[name][0], abs=6e-8)
        assert position.speed_longitude == pytest.approx(values[name][1], abs=6e-8)
    for house in result.houses:
        assert house.longitude == pytest.approx(values[f"house {house.number:2}"][0], abs=6e-8)
    assert result.angles["Ascendant"].longitude == pytest.approx(values["Ascendant"][0], abs=6e-8)
    assert result.angles["Midheaven"].longitude == pytest.approx(values["MC"][0], abs=6e-8)


async def test_service_capacity(service):
    service.active = service.settings.max_concurrent
    result = await service.run("calculate_natal_chart", NatalInput(**PORTO))
    assert not result.success and result.errors[0].code == "SERVICE_BUSY"
    assert not result.positions
    service.active = 0


@pytest.mark.parametrize("day", ["1800-01-02", "2399-12-31"])
async def test_data_coverage_boundaries(service, day):
    request = NatalInput(
        **(PORTO | {"birth_date": day, "birth_time": None, "time_precision": "unknown"})
    )
    result = await service.run("calculate_natal_chart", request)
    assert result.success, result.errors


async def test_start_boundary_prevents_light_time_fallback():
    with pytest.raises(ValidationError):
        NatalInput(**(PORTO | {"birth_date": "1800-01-01"}))
