import hashlib
import json
import threading
from datetime import date
from pathlib import Path

import swisseph as swe

from .config import Settings
from .models import DomainError, House, Position

SIGNS = (
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpio",
    "Sagittarius",
    "Capricorn",
    "Aquarius",
    "Pisces",
)
BODIES = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
    "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO,
}
HOUSE_CODES = {"Placidus": b"P", "WholeSign": b"W", "Equal": b"E"}
EPHEMERIS_MASK = swe.FLG_JPLEPH | swe.FLG_SWIEPH | swe.FLG_MOSEPH
LOCK = threading.RLock()


def zodiac(longitude: float) -> dict:
    longitude %= 360
    return {
        "longitude": longitude,
        "sign": SIGNS[int(longitude // 30)],
        "degree_in_sign": longitude % 30,
    }


def julian_day(day: str, clock: str) -> float:
    d = date.fromisoformat(day)
    hour, minute = map(int, clock.split(":"))
    return swe.julday(d.year, d.month, d.day, hour + minute / 60, swe.GREG_CAL)


def verify_data(settings: Settings) -> str:
    try:
        raw = settings.data_manifest.read_bytes()
        manifest = json.loads(raw)
        for entry in manifest["files"]:
            if Path(entry["name"]).name != entry["name"]:
                raise ValueError("Invalid data filename")
            data = (settings.ephemeris_dir / entry["name"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("Hash mismatch")
        if {e["name"] for e in manifest["files"]} != {"sepl_18.se1", "semo_18.se1"}:
            raise ValueError("Missing data")
        return "swiss_files:sha256:" + hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, KeyError) as exc:
        raise DomainError(
            "EPHEMERIS_DATA_UNAVAILABLE", "Required pinned ephemeris files are missing or invalid."
        ) from exc


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.source = verify_data(settings)

    def _positions(self, jd: float, node_type: str) -> list[Position]:
        bodies = {**BODIES, "NorthNode": swe.MEAN_NODE if node_type == "mean" else swe.TRUE_NODE}
        positions = []
        for name, body in bodies.items():
            values, flags = swe.calc_ut(jd, body, swe.FLG_SWIEPH | swe.FLG_SPEED)
            if flags < 0 or flags & EPHEMERIS_MASK != swe.FLG_SWIEPH:
                raise DomainError(
                    "EPHEMERIS_FALLBACK_REJECTED",
                    "Engine did not use the requested Swiss ephemeris.",
                )
            positions.append(
                Position(
                    body=name,
                    **zodiac(values[0]),
                    latitude=values[1],
                    speed_longitude=values[3],
                    retrograde=values[3] < 0,
                )
            )
        north = positions[-1]
        positions.append(
            Position(
                body="SouthNode",
                **zodiac(north.longitude + 180),
                latitude=-north.latitude,
                speed_longitude=north.speed_longitude,
                retrograde=north.retrograde,
            )
        )
        return positions

    def calculate(
        self,
        jd: float,
        node_type: str,
        location=None,
        house_system=None,
        unknown_time: bool = False,
    ) -> tuple[list[Position], list[House], dict]:
        with LOCK:
            try:
                swe.set_ephe_path(str(self.settings.ephemeris_dir.resolve()))
                positions = self._positions(jd, node_type)
                if unknown_time:
                    samples = [
                        self._positions(jd - 0.5 + step / 48, node_type) for step in range(49)
                    ]
                    for index, position in enumerate(positions):
                        position.uncertainty = "Noon representative only; half-hour samples over supplied day are not rigorous bounds."
                        position.sampled_longitudes = [
                            sample[index].longitude for sample in samples
                        ]
                        position.possible_signs = list(
                            dict.fromkeys(sample[index].sign for sample in samples)
                        )
                houses, angles = [], {}
                if location is not None and house_system is not None:
                    try:
                        cusps, ascmc = swe.houses_ex(
                            jd, location.latitude, location.longitude, HOUSE_CODES[house_system], 0
                        )
                    except swe.Error as exc:
                        raise DomainError(
                            "HOUSE_GEOMETRY_UNDEFINED",
                            "Requested houses cannot be calculated at this latitude; no alternative was selected.",
                        ) from exc
                    houses = [House(number=i + 1, **zodiac(cusp)) for i, cusp in enumerate(cusps)]
                    angles = {
                        "Ascendant": Position(body="Ascendant", **zodiac(ascmc[0])),
                        "Midheaven": Position(body="Midheaven", **zodiac(ascmc[1])),
                    }
                    for position in positions:
                        for i, start in enumerate(cusps):
                            span = (cusps[(i + 1) % 12] - start) % 360
                            if (position.longitude - start) % 360 < span:
                                position.house = i + 1
                                break
                        if position.house is None:
                            raise DomainError(
                                "HOUSE_GEOMETRY_UNDEFINED", "Cannot assign a house consistently."
                            )
                return positions, houses, angles
            except swe.Error as exc:
                raise DomainError(
                    "ENGINE_ERROR", "Astronomical engine failed; no calculated values returned."
                ) from exc
