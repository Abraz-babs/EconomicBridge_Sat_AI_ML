"""Convert NASA FIRMS detections into farmland-protection alert candidates.

Pure functions — no DB, no network, no clock. The DB writer in
`tasks.firms_alerts` consumes the dataclasses produced here.

Rules (first cut — clustering + reverse-geocode come later):

  * Detections at nominal-or-higher confidence are promoted to alerts.
    - VIIRS confidence is a string: 'h' = high, 'n' = nominal, 'l' = low.
      'l' is filtered out.
    - MODIS confidence is 0..100. >= 50 is treated as alert-worthy.
    Why nominal-or-higher (not high-only): the dominant signal in West
    Africa during rainy season is agricultural burning, which VIIRS
    routinely classifies as nominal. Every alert is marked
    human_review_required=True so an officer must approve before SMS
    dispatch — false positives stay invisible to farmers.
    Will tighten back to 'h'-only once we have ground-truth labels
    (Phase A.2 — see ROADMAP.md).
  * Severity is a coarse function of fire radiative power (FRP, megawatts),
    brightness temperature, and the underlying confidence:
       conf='h' OR FRP >= 50  OR  brightness_k >= 340  -> 'critical'
       FRP >= 20  OR  brightness_k >= 320              -> 'high'
       conf='n' (default for VIIRS nominal)             -> 'medium'
       otherwise                                        -> 'low'
  * One detection -> one alert. DBSCAN clustering of co-located pixels
    is deferred to Phase A.3 (will collapse e.g. a 200-pixel burn front
    into a single alert).
  * `model_input_hash` is a stable SHA-256 of
      "{tenant_id}|{lat_3dp}|{lon_3dp}|{detected_date}|{instrument}"
    used by the writer to dedup re-runs of the same FIRMS window.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sources.nasa_firms import FirmsDetection

# Confidence thresholds — see module docstring.
MODIS_HIGH_CONF_PCT: int = 80   # 'h' equivalence
MODIS_MIN_CONF_PCT: int = 50    # alert-worthy floor
VIIRS_HIGH_TOKENS: frozenset[str] = frozenset({"h", "high"})
VIIRS_ACCEPTED_TOKENS: frozenset[str] = frozenset({"h", "high", "n", "nominal"})

# Severity thresholds.
FRP_CRITICAL_MW: float = 50.0
FRP_HIGH_MW: float = 20.0
BRIGHTNESS_CRITICAL_K: float = 340.0
BRIGHTNESS_HIGH_K: float = 320.0

CONFIDENCE_HIGH_SCORE: float = 0.92    # 'h' / MODIS >= 80
CONFIDENCE_NOMINAL_SCORE: float = 0.78  # 'n' / MODIS 50..79


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    """One alert row to be inserted (pre-DB)."""

    tenant_id: str
    alert_type: str  # always 'fire' here; 'conflict' etc. arrive via ML
    severity: str    # critical | high | medium | low
    confidence_score: float
    latitude: float
    longitude: float
    satellite_source: str
    satellite_pass_time: datetime
    model_name: str
    model_version: str
    model_input_hash: str
    affected_area_ha: float | None
    livelihoods_at_risk: int | None  # NULL until reverse-geocode lands
    economic_value_ngn: float | None  # NULL — we don't know the crop yet
    predicted_breach_hours: int | None  # not applicable to fires
    human_review_required: bool


def firms_to_alerts(
    detections: list[FirmsDetection],
    *,
    tenant_id: str,
) -> list[AlertCandidate]:
    """Promote alert-worthy FIRMS detections to alert candidates.

    Args:
        detections: FIRMS rows from `FirmsClient.fetch` (already inside ROI).
        tenant_id: schema-suffix tenant id (e.g. "kebbi").

    Returns:
        List of `AlertCandidate`s. Empty if none of the detections cleared
        the nominal-or-higher confidence floor.
    """
    out: list[AlertCandidate] = []
    for d in detections:
        if not _is_alert_worthy(d):
            continue
        is_high = _is_high_confidence(d)
        out.append(
            AlertCandidate(
                tenant_id=tenant_id,
                alert_type="fire",
                severity=_severity_for(d, is_high=is_high),
                confidence_score=(
                    CONFIDENCE_HIGH_SCORE if is_high
                    else CONFIDENCE_NOMINAL_SCORE
                ),
                latitude=d.latitude,
                longitude=d.longitude,
                satellite_source=_satellite_source_label(d),
                satellite_pass_time=d.detected_at,
                model_name="nasa_firms",
                model_version=_firms_version(d),
                model_input_hash=_input_hash(d, tenant_id),
                affected_area_ha=_pixel_area_ha(d),
                livelihoods_at_risk=None,
                economic_value_ngn=None,
                predicted_breach_hours=None,
                # Fire alerts always require human eyes before SMS dispatch —
                # legitimate ag burning can look identical to wildfire.
                human_review_required=True,
            )
        )
    return out


def _is_alert_worthy(d: FirmsDetection) -> bool:
    conf = (d.confidence or "").strip().lower()
    if not conf:
        return False
    if conf in VIIRS_ACCEPTED_TOKENS:
        return True
    try:
        return int(float(conf)) >= MODIS_MIN_CONF_PCT
    except ValueError:
        return False


def _is_high_confidence(d: FirmsDetection) -> bool:
    conf = (d.confidence or "").strip().lower()
    if not conf:
        return False
    if conf in VIIRS_HIGH_TOKENS:
        return True
    try:
        return int(float(conf)) >= MODIS_HIGH_CONF_PCT
    except ValueError:
        return False


def _severity_for(d: FirmsDetection, *, is_high: bool) -> str:
    frp = d.frp or 0.0
    bright = d.brightness_k or 0.0
    if is_high or frp >= FRP_CRITICAL_MW or bright >= BRIGHTNESS_CRITICAL_K:
        return "critical" if (
            frp >= FRP_CRITICAL_MW or bright >= BRIGHTNESS_CRITICAL_K
        ) else "high"
    if frp >= FRP_HIGH_MW or bright >= BRIGHTNESS_HIGH_K:
        return "high"
    return "medium"


def _satellite_source_label(d: FirmsDetection) -> str:
    inst = (d.instrument or "UNKNOWN").upper()
    sat = (d.satellite or "UNKNOWN").upper()
    return f"NASA FIRMS / {inst} ({sat})"[:100]


def _firms_version(d: FirmsDetection) -> str:
    return (d.raw.get("version") or "NRT")[:20]


def _pixel_area_ha(d: FirmsDetection) -> float | None:
    """Approximate fire-pixel footprint in hectares from scan + track (km)."""
    if d.scan is None or d.track is None:
        return None
    # scan and track are in km. 1 km x 1 km = 100 ha.
    return round(d.scan * d.track * 100.0, 1)


def _input_hash(d: FirmsDetection, tenant_id: str) -> str:
    """Stable SHA-256 for dedup across re-runs of the same FIRMS window."""
    lat_key = f"{d.latitude:.3f}"
    lon_key = f"{d.longitude:.3f}"
    date_key = d.detected_at.date().isoformat()
    inst_key = (d.instrument or "?")
    payload = f"{tenant_id}|{lat_key}|{lon_key}|{date_key}|{inst_key}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
