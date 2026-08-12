"""Per-LGA NDVI climatology — asks "low for November?" not "lower than October?".

WHY THIS EXISTS
---------------
`tasks/shockguard_scan.py` flags drought from a DROP in a rolling NDVI window:
the last 3 readings against the 3 before them. That question has no notion of
what time of year it is, and in West Africa the time of year IS most of the
signal.

Measured 2026-08-12 over the real banked history (public.lga_signal_history:
447 LGAs, Jan 2023 - Jun 2026, 12,672 monthly NDVI points):

  * Seasonal amplitude per LGA (peak month - trough month):
        median 0.362, p10 0.205, p90 0.482
    435 of 436 LGAs swing by more than 0.08 across an ordinary year. 0.08 is
    MIN_ABSOLUTE_DROP, the threshold meant to mean "real vegetation decline",
    so the seasonal cycle alone is ~4.5x the detector's entire sensitivity.

  * Share of LGAs whose NDVI falls >= 0.08 in a single month:
        Nov 55.9%   Dec 43.1%   Jan 27.8%   Oct 26.7%
    At the end of the rains the old detector flags drought across more than
    half the country in one month, at high confidence, for normal weather.

  * Walking the old detector over that history: 2,394 fires / 10,437 windows
    (22.9%), 1,129 of them "critical", peaking Feb-Mar. It was not detecting
    drought; it was detecting the calendar.

THE FIX, AND WHAT IT IS WORTH
-----------------------------
Judge an LGA's NDVI against ITS OWN history for THAT CALENDAR MONTH, so the
seasonal cycle cancels and what is left is "dry for the time of year".

Validated leave-one-year-out (a year is never judged against a normal built
from itself, or the backtest grades its own homework):

    old, rolling window   22.9% of windows fired, monthly rate 3.7% - 57.7%
    new, seasonal          5.8% of readings fired, monthly rate 3.0% - 13.3%
    severity              medium 201 > high 147 > critical 141

The monthly spread is the number that matters: it is what "seasonality removed"
looks like. The severity ladder is now a pyramid with critical rarest, which is
the honest shape.

HONEST LIMIT: we have NO drought ground truth. FEWS NET IPC and NAERLS are not
wired in, so nothing here has been checked against a list of places that were
actually in drought. What is demonstrated is that the seasonal artefact is gone
and the severity ladder is sane — NOT that the remaining detections are
correct. Do not quote an accuracy figure for this detector. When ground truth
arrives, re-run the leave-one-year-out walk against it before making any claim.

This module owns the climatology and the anomaly maths only — no satellite
calls, no event writes — so it can be revalidated offline at zero CDSE cost.
"""
from __future__ import annotations

import collections
import logging
import math
from dataclasses import dataclass
from statistics import mean, median, pstdev

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# ─── Constants, each derived from the measurement above ───────────────────

# Below this an NDVI reading is bare soil, water or cloud — not a vegetation
# measurement. 1% of banked readings are NEGATIVE and 3.2% sit below 0.10.
# Treating those as catastrophic drought is how "ndvi=0.047 vs normal 0.358,
# critical" happens. They are excluded from both the normal and the judgement.
MIN_VALID_NDVI = 0.10

# Distinct years needed in a (LGA, month) cell before we will judge it. Two is
# the floor: one prior year is an anecdote, not a normal. Coverage in the months
# that matter is comfortable — Nov/Dec hold all 447 LGAs at a median of 3 years
# with 99% at >= 2, and Jan is at 100%.
MIN_CLIMATOLOGY_YEARS = 2

# Absolute departure below normal-for-this-month before it counts at all. Same
# 0.08 as the old detector and for the same physical reason — a real decline
# moves NDVI by >= 0.10. What changed is what it is measured AGAINST.
MIN_ANOMALY = 0.08

# Hard floor on the z-score denominator. NOT a tuning knob: shockguard_scan
# records NDVI measurement uncertainty as ~0.02 and we cannot claim a place
# varies by less than we can measure it. 60 of 2,684 well-sampled cells have an
# interannual std below 0.005 — dividing by that is what manufactured z=-151
# and "confidence 1.0" from a flat baseline once before.
MIN_INTERANNUAL_STD = 0.02

# Severity saturation. Chosen because it is the value at which the severity
# ladder becomes a pyramid on real data (medium 201 > high 147 > critical 141);
# at 2.0 — the old NDVI_SCALE, tuned for rolling-window z — 884 of 1,114 fires
# came back "critical", which tells an operator nothing.
NDVI_SCALE = 5.0
THRESHOLD = 0.55


@dataclass(frozen=True, slots=True)
class ClimatologyCell:
    """What one LGA's NDVI normally does in one calendar month."""

    mean: float
    std: float
    years: int

    @property
    def usable(self) -> bool:
        return self.years >= MIN_CLIMATOLOGY_YEARS


@dataclass(frozen=True, slots=True)
class SeasonalAnomaly:
    z: float                 # signed; negative = drier than normal
    anomaly: float           # signed NDVI units below/above normal
    confidence: float
    severity: str
    band: str
    climatology_mean: float
    climatology_std: float   # the denominator actually used (may be pooled)
    climatology_years: int


class Climatology:
    """Per-(tenant, LGA, month) normals, plus a pooled spread estimate.

    The pooled spread is the point of this class. A per-cell standard deviation
    from 2-4 years is a poor estimate, and a poor estimate in a denominator
    produces confident nonsense: a cell that happens to hold two near-identical
    years yields a near-zero std, and any real anomaly then divides out to an
    enormous z. Pooling the interannual spread across every LGA in the same
    tenant-month estimates it from hundreds of samples instead of two, and the
    per-cell value is used only when it is LARGER (a genuinely variable place
    should be harder to alarm about, never easier).
    """

    __slots__ = ("_cells", "_pooled", "_global")

    def __init__(
        self,
        cells: dict[tuple[str, str, int], ClimatologyCell],
        pooled: dict[tuple[str, int], float],
        global_std: float,
    ) -> None:
        self._cells = cells
        self._pooled = pooled
        self._global = global_std

    def cell(self, tenant: str, lga: str, month: int) -> ClimatologyCell | None:
        return self._cells.get((tenant, lga, month))

    def spread(self, tenant: str, month: int, cell_std: float) -> float:
        """The denominator to divide by: the widest defensible estimate."""
        return max(
            cell_std,
            self._pooled.get((tenant, month), self._global),
            MIN_INTERANNUAL_STD,
        )

    def __len__(self) -> int:
        return len(self._cells)


def build_climatology(
    rows: list[tuple[str, str, int, int, float]],
    *,
    exclude_year: int | None = None,
) -> Climatology:
    """Aggregate history rows into per-(tenant, lga, month) normals.

    Args:
        rows: (tenant_id, lga, year, month, ndvi_mean), one per observation.
        exclude_year: drop this year before aggregating. Used by the validation
            walk so a year is never judged against a normal computed from
            itself.
    """
    buckets: dict[tuple[str, str, int], list[float]] = collections.defaultdict(list)
    for tenant, lga, year, month, value in rows:
        if exclude_year is not None and year == exclude_year:
            continue
        if value < MIN_VALID_NDVI:      # cloud / water / bare soil, not vegetation
            continue
        buckets[(tenant, lga, month)].append(value)

    cells: dict[tuple[str, str, int], ClimatologyCell] = {}
    for key, values in buckets.items():
        cells[key] = ClimatologyCell(
            mean=mean(values),
            std=pstdev(values) if len(values) > 1 else 0.0,
            years=len(values),
        )

    # Pool only from cells with >= 3 years; a 2-year std is too noisy to
    # contribute to an estimate whose whole purpose is to be stable.
    pool: dict[tuple[str, int], list[float]] = collections.defaultdict(list)
    for (tenant, _lga, month), c in cells.items():
        if c.years >= 3:
            pool[(tenant, month)].append(c.std)
    pooled = {k: median(v) for k, v in pool.items() if v}
    everything = [s for v in pool.values() for s in v]
    global_std = median(everything) if everything else MIN_INTERANNUAL_STD

    return Climatology(cells, pooled, global_std)


def _severity(c: float) -> str:
    if c >= 0.82:
        return "critical"
    if c >= 0.68:
        return "high"
    return "medium"


def _band(c: float) -> str:
    if c >= 0.75:
        return "HIGH"
    if c >= 0.55:
        return "MEDIUM"
    return "LOW"


def seasonal_drought(
    ndvi: float, climatology: Climatology, *, tenant: str, lga: str, month: int,
) -> SeasonalAnomaly | None:
    """Judge one NDVI reading against its own month's normal.

    Returns None when the reading is unremarkable for the time of year, when the
    reading is not a valid vegetation measurement, and when there is no usable
    baseline — no climatology means no claim. Falling back to the rolling-window
    comparison would reintroduce exactly the seasonal blindness this exists to
    remove, so there is deliberately no fallback.
    """
    if ndvi < MIN_VALID_NDVI:
        return None

    cell = climatology.cell(tenant, lga, month)
    if cell is None or not cell.usable:
        return None

    anomaly = ndvi - cell.mean                 # negative = drier than normal
    if -anomaly < MIN_ANOMALY:                 # Gate 1 — physically meaningful
        return None

    std = climatology.spread(tenant, month, cell.std)
    z = anomaly / std                          # Gate 2 — unusual for this place
    confidence = math.tanh(max(0.0, -z) / NDVI_SCALE)
    if confidence < THRESHOLD:
        return None

    return SeasonalAnomaly(
        z=round(z, 3),
        anomaly=round(anomaly, 4),
        confidence=round(confidence, 4),
        severity=_severity(confidence),
        band=_band(confidence),
        climatology_mean=round(cell.mean, 4),
        climatology_std=round(std, 4),
        climatology_years=cell.years,
    )


async def load_climatology_rows(
    session: AsyncSession, *, tenant_id: str | None = None,
) -> list[tuple[str, str, int, int, float]]:
    """Read banked monthly NDVI out of public.lga_signal_history."""
    sql = (
        "SELECT tenant_id, lga, EXTRACT(YEAR FROM period_start)::int AS y, "
        "       EXTRACT(MONTH FROM period_start)::int AS m, mean "
        "  FROM public.lga_signal_history "
        " WHERE signal = 'ndvi' AND mean IS NOT NULL"
    )
    params: dict[str, object] = {}
    if tenant_id:
        sql += " AND tenant_id = :t"
        params["t"] = tenant_id
    rows = (await session.execute(text(sql), params)).all()
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
