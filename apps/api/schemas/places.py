"""Field directions — shared by every module that reports a real point.

A NearestPlace goes ONLY on a coordinate that is a real point on the ground: a
detection's measured box, a fire, a geotagged photo, a checked plot. Never on
an LGA centroid standing in for a whole area (a storm, an LGA's crop health):
"4 km NE of <village>" on a centroid would send a team to an arbitrary village
on a false trail. Each module decides that before asking services/places.py.

Source: GRID3 NGA Settlement Names, CC BY 4.0 — credit it wherever shown.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class GeoPoint(BaseModel):
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class NearestPlace(BaseModel):
    """The named village nearest a point, for field teams."""

    name: str
    ward: str | None = None
    lga: str | None = None
    distance_km: float
    # Compass direction FROM the village TO the point; None when it is at the
    # village itself.
    direction: str | None = None
    location: GeoPoint


class NearestPlacesData(BaseModel):
    # Same order as the request; None where no village is known.
    places: list[NearestPlace | None]
