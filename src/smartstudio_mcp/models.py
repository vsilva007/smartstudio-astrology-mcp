from datetime import date
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Text = Annotated[
    str, StringConstraints(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$")
]
Clock = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
Longitude = Annotated[float, Field(ge=0, lt=360, allow_inf_nan=False, strict=True)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)]
GeoLongitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)]
AspectName = Literal["conjunction", "sextile", "square", "trine", "opposition"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class PlaceInput(Model):
    city: Text
    country: Text
    region: Text | None = None

    @field_validator("city", "country", "region")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Place must not be blank")
        return value


class ReferenceInput(Model):
    reference_date: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    reference_time: Clock
    calculation_mode: Literal["literal_no_timezone"] = "literal_no_timezone"
    zodiac: Literal["tropical"] = "tropical"
    node_type: Literal["mean", "true"] = "mean"

    @field_validator("reference_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        parsed = date.fromisoformat(value)
        if not date(1800, 1, 2) <= parsed <= date(2399, 12, 31):
            raise ValueError("Supported Gregorian dates: 1800-01-02 through 2399-12-31")
        return value


class NatalInput(PlaceInput):
    birth_date: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    birth_time: Clock | None = None
    latitude: Latitude | None = None
    longitude: GeoLongitude | None = None
    zodiac: Literal["tropical"] = "tropical"
    house_system: Literal["Placidus", "WholeSign", "Equal"] = "Placidus"
    node_type: Literal["mean", "true"] = "mean"
    time_precision: Literal["exact", "approximate", "unknown"] = "unknown"
    calculation_mode: Literal["literal_no_timezone"] = "literal_no_timezone"
    require_verified_instant: bool = False

    @field_validator("birth_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        return ReferenceInput.valid_date(value)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Supply both coordinates or neither")
        if (self.birth_time is None) != (self.time_precision == "unknown"):
            raise ValueError(
                "Omit time only with time_precision=unknown; supplied time requires exact or approximate"
            )
        return self


class OrbConfig(Model):
    conjunction: Annotated[float, Field(ge=0, le=15)] = 8.0
    sextile: Annotated[float, Field(ge=0, le=15)] = 4.0
    square: Annotated[float, Field(ge=0, le=15)] = 6.0
    trine: Annotated[float, Field(ge=0, le=15)] = 6.0
    opposition: Annotated[float, Field(ge=0, le=15)] = 8.0


class AspectInput(Model):
    longitudes: Annotated[dict[Text, Longitude], Field(min_length=2, max_length=32)]
    orbs: OrbConfig = Field(default_factory=OrbConfig)


class Location(Model):
    city: str
    country: str
    region: str | None = None
    latitude: Latitude
    longitude: GeoLongitude
    source: str
    confidence: Literal["provider_unscored", "user_supplied", "curated"]
    ambiguous: bool = False


class Position(Model):
    body: str
    longitude: Longitude
    latitude: float = 0.0
    sign: str
    degree_in_sign: Annotated[float, Field(ge=0, lt=30)]
    speed_longitude: float | None = None
    retrograde: bool | None = None
    house: Annotated[int, Field(ge=1, le=12)] | None = None
    uncertainty: str | None = None
    sampled_longitudes: list[float] = Field(default_factory=list)
    possible_signs: list[str] = Field(default_factory=list)


class House(Model):
    number: Annotated[int, Field(ge=1, le=12)]
    longitude: Longitude
    sign: str
    degree_in_sign: Annotated[float, Field(ge=0, lt=30)]


class Aspect(Model):
    body1: str
    body2: str
    aspect: AspectName
    exact_angle: float
    separation: float
    orb: float
    allowed_orb: float


class Issue(Model):
    code: str
    message: str


class Result(Model):
    success: bool = True
    calculation_mode: Literal["literal_no_timezone"] = "literal_no_timezone"
    input: dict
    resolved_location: Location | None = None
    time_reference: str = "supplied_clock_used_as_ut"
    precision_status: str = "civil_time_not_utc_verified"
    engine: str = "Swiss Ephemeris"
    engine_version: str
    ephemeris_source: str = "not_used"
    zodiac: str | None = None
    house_system: str | None = None
    positions: list[Position] = Field(default_factory=list)
    houses: list[House] = Field(default_factory=list)
    angles: dict[str, Position] = Field(default_factory=dict)
    aspects: list[Aspect] = Field(default_factory=list)
    warnings: list[Issue] = Field(default_factory=list)
    errors: list[Issue] = Field(default_factory=list)
    candidates: list[Location] = Field(default_factory=list)
    ambiguous: bool = False
    julian_day: float | None = None
    effective_clock: str | None = None
    source_url: str = "/source"


class DomainError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(code)
