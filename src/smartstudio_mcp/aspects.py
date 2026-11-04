from itertools import combinations

from .models import Aspect, OrbConfig

ANGLES = {"conjunction": 0, "sextile": 60, "square": 90, "trine": 120, "opposition": 180}


def calculate(longitudes: dict[str, float], orbs: OrbConfig | None = None) -> list[Aspect]:
    limits = (orbs or OrbConfig()).model_dump()
    aspects = []
    for (body1, a), (body2, b) in combinations(sorted(longitudes.items()), 2):
        separation = abs((a - b + 180) % 360 - 180)
        for name, angle in ANGLES.items():
            orb = abs(separation - angle)
            if orb <= limits[name]:
                aspects.append(
                    Aspect(
                        body1=body1,
                        body2=body2,
                        aspect=name,
                        exact_angle=float(angle),
                        separation=separation,
                        orb=orb,
                        allowed_orb=limits[name],
                    )
                )
    return aspects
