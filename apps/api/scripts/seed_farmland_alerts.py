"""Seed realistic farmland alerts into the pilot tenant schemas.

Usage (from apps/api/ with the venv active):
    python -m scripts.seed_farmland_alerts

Idempotent — re-running deletes any row whose `model_name = 'seed'` and
re-inserts the canonical dev fixture. Real ML inferences (model_name like
'conflict_predictor_v1') are never touched.

The fixture mirrors what FarmlandPanel.tsx ships as hardcoded data so the
visual continuity between mock and live mode is intentional.

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

# Make `apps/api/` importable when invoked as a script.
API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402

SEED_MODEL_NAME = "seed"


@dataclass(frozen=True, slots=True)
class SeedAlert:
    tenant: str
    alert_type: str
    severity: str
    status: str
    zone_name: str
    lga: str
    lon: float
    lat: float
    confidence_score: float
    affected_area_ha: float
    livelihoods_at_risk: int
    economic_value_ngn: float
    predicted_breach_hours: int | None
    satellite_source: str
    hours_ago: float
    human_review_required: bool
    agencies_notified: Sequence[str]


# Anchored to the four pilot-state LGAs that FarmlandPanel.tsx ships in mock
# mode, plus a few extras to populate other tenants.
SEED_ALERTS: tuple[SeedAlert, ...] = (
    # ── Kebbi ─────────────────────────────────────────────────────────
    SeedAlert(
        tenant="kebbi", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Argungu North agro-corridor",
        lga="Argungu", lon=4.5253, lat=12.7444,
        confidence_score=0.94,
        affected_area_ha=82.0, livelihoods_at_risk=412,
        economic_value_ngn=18_500_000, predicted_breach_hours=7,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=0.25, human_review_required=False,
        agencies_notified=("NEMA", "Min. Agriculture", "Kebbi State Agric. Dept."),
    ),
    SeedAlert(
        tenant="kebbi", alert_type="conflict", severity="medium",
        status="resolved",
        zone_name="Birnin Kebbi farmlands",
        lga="Birnin Kebbi", lon=4.1994, lat=12.4539,
        confidence_score=0.88,
        affected_area_ha=24.0, livelihoods_at_risk=130,
        economic_value_ngn=4_800_000, predicted_breach_hours=None,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=22.0, human_review_required=False,
        agencies_notified=("NEMA",),
    ),

    # ── Zamfara ───────────────────────────────────────────────────────
    SeedAlert(
        tenant="zamfara", alert_type="conflict", severity="critical",
        status="acknowledged",
        zone_name="Anka boundary breach",
        lga="Anka", lon=5.9333, lat=12.1056,
        confidence_score=0.91,
        affected_area_ha=58.0, livelihoods_at_risk=290,
        economic_value_ngn=11_200_000, predicted_breach_hours=4,
        satellite_source="Copernicus Sentinel-1 SAR + NDVI",
        hours_ago=0.6, human_review_required=False,
        agencies_notified=("NEMA", "Min. Agriculture", "Zamfara MoAH"),
    ),
    SeedAlert(
        tenant="zamfara", alert_type="drought", severity="medium",
        status="pending_review",
        zone_name="Gusau outskirts",
        lga="Gusau", lon=6.6644, lat=12.1704,
        confidence_score=0.78,
        affected_area_ha=420.0, livelihoods_at_risk=2_100,
        economic_value_ngn=38_000_000, predicted_breach_hours=None,
        satellite_source="MODIS Terra (MOD11A1)",
        hours_ago=5.0, human_review_required=True,
        agencies_notified=("Zamfara MoAH",),
    ),

    # ── Plateau ───────────────────────────────────────────────────────
    SeedAlert(
        tenant="plateau", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Shendam western boundary",
        lga="Shendam", lon=9.5380, lat=8.8833,
        confidence_score=0.87,
        affected_area_ha=46.0, livelihoods_at_risk=215,
        economic_value_ngn=7_400_000, predicted_breach_hours=48,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=1.1, human_review_required=False,
        agencies_notified=("Plateau State Mediators",),
    ),

    # ── Kaduna ────────────────────────────────────────────────────────
    SeedAlert(
        tenant="kaduna", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Kachia sorghum belt",
        lga="Kachia", lon=7.9490, lat=9.8676,
        confidence_score=0.82,
        affected_area_ha=63.0, livelihoods_at_risk=298,
        economic_value_ngn=8_950_000, predicted_breach_hours=72,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=2.4, human_review_required=False,
        agencies_notified=("Kaduna Extension Officers",),
    ),
    SeedAlert(
        tenant="kaduna", alert_type="flood", severity="medium",
        status="acknowledged",
        zone_name="Kaduna river overflow",
        lga="Kaduna South", lon=7.4350, lat=10.5180,
        confidence_score=0.84,
        affected_area_ha=180.0, livelihoods_at_risk=920,
        economic_value_ngn=22_500_000, predicted_breach_hours=24,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=8.0, human_review_required=False,
        agencies_notified=("NEMA", "Kaduna SEMA"),
    ),

    # ── Benue ─────────────────────────────────────────────────────────
    SeedAlert(
        tenant="benue", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Guma farmlands",
        lga="Guma", lon=8.9667, lat=7.7833,
        confidence_score=0.93,
        affected_area_ha=110.0, livelihoods_at_risk=540,
        economic_value_ngn=24_800_000, predicted_breach_hours=6,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=0.4, human_review_required=False,
        agencies_notified=("NEMA", "Benue MoA", "Min. Agriculture"),
    ),

    # ── Niger ─────────────────────────────────────────────────────────
    SeedAlert(
        tenant="niger", alert_type="crop_disease", severity="medium",
        status="pending_review",
        zone_name="Mokwa cassava plots",
        lga="Mokwa", lon=5.0500, lat=9.2933,
        confidence_score=0.81,
        affected_area_ha=340.0, livelihoods_at_risk=1_280,
        economic_value_ngn=14_200_000, predicted_breach_hours=None,
        satellite_source="Sentinel-2 MSI NDVI",
        hours_ago=18.0, human_review_required=True,
        agencies_notified=("FAO Nigeria",),
    ),
)


async def _seed_for_tenant(session_factory, tenant: str, fixtures: list[SeedAlert]) -> None:
    schema = f"tenant_{tenant}"
    async with session_factory() as session:
        # Pin to this tenant for the lifetime of the session
        await session.execute(text(f"SET search_path TO {schema}, public"))
        # Remove any existing seed rows so the script is idempotent
        await session.execute(
            text("DELETE FROM alert_events WHERE model_name = :n"),
            {"n": SEED_MODEL_NAME},
        )
        now = datetime.now(timezone.utc)
        for f in fixtures:
            created_at = now - timedelta(hours=f.hours_ago)
            await session.execute(
                text(
                    """
                    INSERT INTO alert_events (
                        tenant_id, alert_type, severity, status,
                        zone_name, lga,
                        location,
                        confidence_score, affected_area_ha,
                        livelihoods_at_risk, economic_value_ngn,
                        predicted_breach_hours,
                        satellite_source, satellite_pass_time,
                        model_name, model_version,
                        human_review_required,
                        agencies_notified,
                        created_at, updated_at
                    ) VALUES (
                        :tenant_id, :alert_type, :severity, :status,
                        :zone_name, :lga,
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                        :confidence_score, :affected_area_ha,
                        :livelihoods_at_risk, :economic_value_ngn,
                        :predicted_breach_hours,
                        :satellite_source, :satellite_pass_time,
                        :model_name, :model_version,
                        :human_review_required,
                        :agencies_notified,
                        :created_at, :created_at
                    )
                    """
                ),
                {
                    "tenant_id": f.tenant,
                    "alert_type": f.alert_type,
                    "severity": f.severity,
                    "status": f.status,
                    "zone_name": f.zone_name,
                    "lga": f.lga,
                    "lon": f.lon,
                    "lat": f.lat,
                    "confidence_score": f.confidence_score,
                    "affected_area_ha": f.affected_area_ha,
                    "livelihoods_at_risk": f.livelihoods_at_risk,
                    "economic_value_ngn": f.economic_value_ngn,
                    "predicted_breach_hours": f.predicted_breach_hours,
                    "satellite_source": f.satellite_source,
                    "satellite_pass_time": created_at,
                    "model_name": SEED_MODEL_NAME,
                    "model_version": "0.0.1",
                    "human_review_required": f.human_review_required,
                    "agencies_notified": list(f.agencies_notified),
                    "created_at": created_at,
                },
            )
        await session.commit()


async def main() -> None:
    by_tenant: dict[str, list[SeedAlert]] = {}
    for a in SEED_ALERTS:
        by_tenant.setdefault(a.tenant, []).append(a)

    session_factory = get_session_factory()
    for tenant, fixtures in by_tenant.items():
        await _seed_for_tenant(session_factory, tenant, fixtures)
        print(f"[seed] tenant_{tenant}: {len(fixtures)} alerts")

    await get_engine().dispose()
    print(f"\n[seed] done — {sum(len(v) for v in by_tenant.values())} alerts across "
          f"{len(by_tenant)} tenants")


if __name__ == "__main__":
    asyncio.run(main())
