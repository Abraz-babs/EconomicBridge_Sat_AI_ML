"""Response models for coordinate → administrative-unit resolution."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ResolvedUnit(BaseModel):
    """The administrative unit nearest a coordinate, as we know it.

    All three fields are null together when the point is outside our pilot
    coverage — we would rather say nothing than name a unit 400 km away.
    """

    tenant_id: str | None = Field(
        default=None,
        description="Pilot slug the nearest unit belongs to (e.g. 'kebbi').",
    )
    lga: str | None = Field(
        default=None,
        description="LGA / district name, spelled as the rest of the platform spells it.",
    )
    distance_km: float | None = Field(
        default=None,
        description=(
            "Kilometres from the point to that unit's centroid. This is a "
            "nearest-centroid result, not point-in-polygon: near a boundary the "
            "true containing unit may differ, and this number is how a caller "
            "judges how much to trust the answer."
        ),
    )
