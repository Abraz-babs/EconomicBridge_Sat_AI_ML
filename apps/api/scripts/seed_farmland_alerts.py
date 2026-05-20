"""Seed realistic farmland alerts into the pilot tenant schemas.

Usage (from apps/api/ with the venv active):
    python -m scripts.seed_farmland_alerts
    python -m scripts.seed_farmland_alerts --purge-firms

Idempotent — re-running deletes any row whose `model_name = 'seed'` and
re-inserts the canonical dev fixture. Real ML inferences (model_name like
'conflict_predictor_v1') are never touched.

`--purge-firms` additionally soft-deletes every row with model_name =
'nasa_firms' across every tenant. Useful for clearing dev pipeline test
output without losing the raw heat_signatures audit trail.

The fixture mirrors what FarmlandPanel.tsx ships as hardcoded data so the
visual continuity between mock and live mode is intentional.

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import argparse
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
FIRMS_MODEL_NAME = "nasa_firms"


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

    # ── Nasarawa (Middle Belt — herder-farmer flashpoint) ────────────
    SeedAlert(
        tenant="nasarawa", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Awe yam belt encroachment",
        lga="Awe", lon=9.0411, lat=8.1086,
        confidence_score=0.95,
        affected_area_ha=128.0, livelihoods_at_risk=620,
        economic_value_ngn=28_900_000, predicted_breach_hours=5,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=0.3, human_review_required=False,
        agencies_notified=("NEMA", "Min. Agriculture", "Nasarawa MoAH"),
    ),
    SeedAlert(
        tenant="nasarawa", alert_type="conflict", severity="high",
        status="acknowledged",
        zone_name="Doma sorghum corridor",
        lga="Doma", lon=8.3917, lat=8.3786,
        confidence_score=0.88,
        affected_area_ha=72.0, livelihoods_at_risk=315,
        economic_value_ngn=11_800_000, predicted_breach_hours=22,
        satellite_source="Copernicus Sentinel-1 SAR + heat",
        hours_ago=2.0, human_review_required=False,
        agencies_notified=("Nasarawa Mediators", "NEMA"),
    ),
    SeedAlert(
        tenant="nasarawa", alert_type="conflict", severity="medium",
        status="resolved",
        zone_name="Lafia outskirts",
        lga="Lafia", lon=8.5167, lat=8.4933,
        confidence_score=0.86,
        affected_area_ha=38.0, livelihoods_at_risk=180,
        economic_value_ngn=6_400_000, predicted_breach_hours=None,
        satellite_source="Sentinel-2 MSI",
        hours_ago=30.0, human_review_required=False,
        agencies_notified=("Nasarawa MoAH",),
    ),

    # ── FCT (Federal Capital Territory — Abuja periphery) ────────────
    SeedAlert(
        tenant="fct", alert_type="flood", severity="medium",
        status="pending_review",
        zone_name="Gwagwalada flood plain",
        lga="Gwagwalada", lon=7.0810, lat=8.9437,
        confidence_score=0.83,
        affected_area_ha=210.0, livelihoods_at_risk=890,
        economic_value_ngn=18_200_000, predicted_breach_hours=36,
        satellite_source="Copernicus Sentinel-1 SAR (flood mask)",
        hours_ago=4.0, human_review_required=False,
        agencies_notified=("FCT Emergency Mgmt.", "NEMA"),
    ),
    SeedAlert(
        tenant="fct", alert_type="crop_disease", severity="low",
        status="pending_review",
        zone_name="Kwali rice scheme",
        lga="Kwali", lon=7.0167, lat=8.8833,
        confidence_score=0.74,
        affected_area_ha=46.0, livelihoods_at_risk=128,
        economic_value_ngn=2_100_000, predicted_breach_hours=None,
        satellite_source="Sentinel-2 MSI NDVI",
        hours_ago=14.0, human_review_required=True,
        agencies_notified=("FCT Agric. Dept.",),
    ),

    # ── Ghana (Upper East — Bawku conflict belt) ─────────────────────
    SeedAlert(
        tenant="ghana", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Bawku farmland boundary",
        lga="Bawku Municipal", lon=-0.2422, lat=11.0586,
        confidence_score=0.89,
        affected_area_ha=64.0, livelihoods_at_risk=280,
        economic_value_ngn=0.0,  # Ghana — not tracked in NGN
        predicted_breach_hours=18,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=1.5, human_review_required=False,
        agencies_notified=("Ghana NADMO", "Min. of Food & Agric."),
    ),
    SeedAlert(
        tenant="ghana", alert_type="drought", severity="medium",
        status="pending_review",
        zone_name="Tamale northern outskirts",
        lga="Tamale Metropolitan", lon=-0.8333, lat=9.4008,
        confidence_score=0.79,
        affected_area_ha=380.0, livelihoods_at_risk=1_540,
        economic_value_ngn=0.0,
        predicted_breach_hours=None,
        satellite_source="MODIS Terra (MOD13A2 NDVI)",
        hours_ago=9.0, human_review_required=True,
        agencies_notified=("Ghana NADMO",),
    ),

    # ── Senegal (Casamance — south, conflict-affected) ────────────────
    SeedAlert(
        tenant="senegal", alert_type="conflict", severity="medium",
        status="acknowledged",
        zone_name="Ziguinchor agro-belt",
        lga="Ziguinchor Region", lon=-16.2733, lat=12.5681,
        confidence_score=0.82,
        affected_area_ha=92.0, livelihoods_at_risk=410,
        economic_value_ngn=0.0,
        predicted_breach_hours=42,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=3.0, human_review_required=False,
        agencies_notified=("ANACIM", "Direction de la Protection des Végétaux"),
    ),
    SeedAlert(
        tenant="senegal", alert_type="flood", severity="high",
        status="pending_review",
        zone_name="Saint-Louis delta",
        lga="Saint-Louis Region", lon=-16.4583, lat=16.0317,
        confidence_score=0.87,
        affected_area_ha=520.0, livelihoods_at_risk=2_180,
        economic_value_ngn=0.0,
        predicted_breach_hours=28,
        satellite_source="Copernicus Sentinel-1 SAR (flood mask)",
        hours_ago=6.0, human_review_required=False,
        agencies_notified=("Sénégal Civil Protection", "ANACIM"),
    ),

    # ─── Rebalance fixtures (added 2026-05-20) ───────────────────────────
    # Goal: every active tenant carries 4-6 encroachment / conflict alerts
    # so the dashboard reads as a 10-state platform with encroachment as
    # the headline, not a Kebbi-only fire feed. Real LGA names + locally
    # documented herder-farmer / banditry corridors.

    # ── Kebbi (4 more conflict) ──────────────────────────────────────────
    SeedAlert(
        tenant="kebbi", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Yauri pastoral boundary",
        lga="Yauri", lon=4.7833, lat=10.7833,
        confidence_score=0.89,
        affected_area_ha=54.0, livelihoods_at_risk=240,
        economic_value_ngn=9_600_000, predicted_breach_hours=18,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=1.8, human_review_required=False,
        agencies_notified=("Kebbi State Agric. Dept.",),
    ),
    SeedAlert(
        tenant="kebbi", alert_type="conflict", severity="high",
        status="acknowledged",
        zone_name="Bagudo border farms",
        lga="Bagudo", lon=4.25, lat=11.4,
        confidence_score=0.85,
        affected_area_ha=68.0, livelihoods_at_risk=310,
        economic_value_ngn=12_400_000, predicted_breach_hours=26,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=5.2, human_review_required=False,
        agencies_notified=("Kebbi State Agric. Dept.", "NEMA"),
    ),
    SeedAlert(
        tenant="kebbi", alert_type="conflict", severity="medium",
        status="pending_review",
        zone_name="Maiyama irrigation belt",
        lga="Maiyama", lon=4.2167, lat=12.3667,
        confidence_score=0.81,
        affected_area_ha=42.0, livelihoods_at_risk=190,
        economic_value_ngn=6_200_000, predicted_breach_hours=None,
        satellite_source="Sentinel-2 MSI NDVI",
        hours_ago=11.0, human_review_required=True,
        agencies_notified=("Kebbi State Agric. Dept.",),
    ),
    SeedAlert(
        tenant="kebbi", alert_type="conflict", severity="medium",
        status="resolved",
        zone_name="Gwandu mango belt",
        lga="Gwandu", lon=4.6, lat=12.5,
        confidence_score=0.78,
        affected_area_ha=31.0, livelihoods_at_risk=145,
        economic_value_ngn=4_100_000, predicted_breach_hours=None,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=58.0, human_review_required=False,
        agencies_notified=("Kebbi State Agric. Dept.",),
    ),

    # ── Benue (5 more — highest herder-farmer conflict rate, CLAUDE.md §10) ──
    SeedAlert(
        tenant="benue", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Agatu yam corridor",
        lga="Agatu", lon=8.0167, lat=7.6833,
        confidence_score=0.94,
        affected_area_ha=145.0, livelihoods_at_risk=720,
        economic_value_ngn=32_500_000, predicted_breach_hours=4,
        satellite_source="Copernicus Sentinel-1 SAR + heat",
        hours_ago=0.5, human_review_required=False,
        agencies_notified=("NEMA", "Benue MoA", "Min. Agriculture"),
    ),
    SeedAlert(
        tenant="benue", alert_type="conflict", severity="critical",
        status="acknowledged",
        zone_name="Logo river basin farms",
        lga="Logo", lon=9.2167, lat=7.7,
        confidence_score=0.92,
        affected_area_ha=98.0, livelihoods_at_risk=485,
        economic_value_ngn=22_100_000, predicted_breach_hours=8,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=2.3, human_review_required=False,
        agencies_notified=("NEMA", "Benue MoA"),
    ),
    SeedAlert(
        tenant="benue", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Tarka Tiv heartland",
        lga="Tarka", lon=9.0, lat=7.4,
        confidence_score=0.88,
        affected_area_ha=72.0, livelihoods_at_risk=340,
        economic_value_ngn=15_300_000, predicted_breach_hours=14,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=4.0, human_review_required=False,
        agencies_notified=("Benue MoA",),
    ),
    SeedAlert(
        tenant="benue", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Ukum rice plots",
        lga="Ukum", lon=9.0833, lat=7.0833,
        confidence_score=0.86,
        affected_area_ha=58.0, livelihoods_at_risk=265,
        economic_value_ngn=11_800_000, predicted_breach_hours=22,
        satellite_source="Sentinel-2 MSI NDVI",
        hours_ago=7.5, human_review_required=False,
        agencies_notified=("Benue MoA", "NEMA"),
    ),
    SeedAlert(
        tenant="benue", alert_type="conflict", severity="medium",
        status="resolved",
        zone_name="Makurdi periphery",
        lga="Makurdi", lon=8.5, lat=7.7333,
        confidence_score=0.79,
        affected_area_ha=34.0, livelihoods_at_risk=160,
        economic_value_ngn=5_400_000, predicted_breach_hours=None,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=40.0, human_review_required=False,
        agencies_notified=("Benue MoA",),
    ),

    # ── Plateau (4 more — Jos Plateau massacre belt) ────────────────────
    SeedAlert(
        tenant="plateau", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Bassa cattle corridor",
        lga="Bassa", lon=8.5833, lat=10.0167,
        confidence_score=0.93,
        affected_area_ha=88.0, livelihoods_at_risk=420,
        economic_value_ngn=18_700_000, predicted_breach_hours=6,
        satellite_source="Copernicus Sentinel-1 SAR + heat",
        hours_ago=0.7, human_review_required=False,
        agencies_notified=("NEMA", "Plateau State Mediators"),
    ),
    SeedAlert(
        tenant="plateau", alert_type="conflict", severity="critical",
        status="acknowledged",
        zone_name="Riyom mixed-farming zone",
        lga="Riyom", lon=8.7333, lat=9.7333,
        confidence_score=0.90,
        affected_area_ha=64.0, livelihoods_at_risk=298,
        economic_value_ngn=12_900_000, predicted_breach_hours=12,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=3.4, human_review_required=False,
        agencies_notified=("Plateau State Mediators", "NEMA"),
    ),
    SeedAlert(
        tenant="plateau", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Bokkos tin-mining edge",
        lga="Bokkos", lon=9.0, lat=9.3,
        confidence_score=0.84,
        affected_area_ha=48.0, livelihoods_at_risk=210,
        economic_value_ngn=8_600_000, predicted_breach_hours=20,
        satellite_source="Sentinel-2 MSI",
        hours_ago=9.0, human_review_required=False,
        agencies_notified=("Plateau State Mediators",),
    ),
    SeedAlert(
        tenant="plateau", alert_type="conflict", severity="medium",
        status="resolved",
        zone_name="Vom dairy belt",
        lga="Jos South", lon=8.785, lat=9.6917,
        confidence_score=0.76,
        affected_area_ha=29.0, livelihoods_at_risk=140,
        economic_value_ngn=4_300_000, predicted_breach_hours=None,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=72.0, human_review_required=False,
        agencies_notified=("Plateau State Mediators",),
    ),

    # ── Kaduna (4 more — southern Kaduna flashpoints) ────────────────────
    SeedAlert(
        tenant="kaduna", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Birnin Gwari banditry corridor",
        lga="Birnin Gwari", lon=6.7667, lat=11.0167,
        confidence_score=0.92,
        affected_area_ha=156.0, livelihoods_at_risk=780,
        economic_value_ngn=34_200_000, predicted_breach_hours=5,
        satellite_source="Copernicus Sentinel-1 SAR + heat",
        hours_ago=0.6, human_review_required=False,
        agencies_notified=("NEMA", "Kaduna SEMA", "Kaduna Extension Officers"),
    ),
    SeedAlert(
        tenant="kaduna", alert_type="conflict", severity="high",
        status="acknowledged",
        zone_name="Zangon Kataf yam belt",
        lga="Zangon Kataf", lon=8.0667, lat=9.7833,
        confidence_score=0.87,
        affected_area_ha=68.0, livelihoods_at_risk=312,
        economic_value_ngn=13_400_000, predicted_breach_hours=16,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=3.0, human_review_required=False,
        agencies_notified=("Kaduna Extension Officers",),
    ),
    SeedAlert(
        tenant="kaduna", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Giwa northern grazing area",
        lga="Giwa", lon=7.4333, lat=11.275,
        confidence_score=0.83,
        affected_area_ha=52.0, livelihoods_at_risk=240,
        economic_value_ngn=9_200_000, predicted_breach_hours=22,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=6.4, human_review_required=False,
        agencies_notified=("Kaduna Extension Officers", "NEMA"),
    ),
    SeedAlert(
        tenant="kaduna", alert_type="conflict", severity="medium",
        status="pending_review",
        zone_name="Soba sorghum plots",
        lga="Soba", lon=7.8833, lat=10.95,
        confidence_score=0.78,
        affected_area_ha=38.0, livelihoods_at_risk=175,
        economic_value_ngn=5_900_000, predicted_breach_hours=None,
        satellite_source="Sentinel-2 MSI NDVI",
        hours_ago=14.0, human_review_required=True,
        agencies_notified=("Kaduna Extension Officers",),
    ),

    # ── Niger (4 new — Shiroro dam belt + banditry corridor) ─────────────
    SeedAlert(
        tenant="niger", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Shiroro dam-edge farms",
        lga="Shiroro", lon=6.8333, lat=9.7333,
        confidence_score=0.91,
        affected_area_ha=124.0, livelihoods_at_risk=590,
        economic_value_ngn=24_800_000, predicted_breach_hours=8,
        satellite_source="Copernicus Sentinel-1 SAR + heat",
        hours_ago=1.1, human_review_required=False,
        agencies_notified=("NEMA", "Min. Agriculture", "Niger State SEMA"),
    ),
    SeedAlert(
        tenant="niger", alert_type="conflict", severity="critical",
        status="acknowledged",
        zone_name="Kontagora pastoral corridor",
        lga="Kontagora", lon=5.4667, lat=10.4,
        confidence_score=0.89,
        affected_area_ha=92.0, livelihoods_at_risk=410,
        economic_value_ngn=17_200_000, predicted_breach_hours=15,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=4.5, human_review_required=False,
        agencies_notified=("Niger State SEMA", "NEMA"),
    ),
    SeedAlert(
        tenant="niger", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Bida Nupe rice belt",
        lga="Bida", lon=6.0167, lat=9.0833,
        confidence_score=0.83,
        affected_area_ha=54.0, livelihoods_at_risk=248,
        economic_value_ngn=9_700_000, predicted_breach_hours=20,
        satellite_source="Sentinel-2 MSI NDVI",
        hours_ago=8.0, human_review_required=False,
        agencies_notified=("Niger State SEMA",),
    ),
    SeedAlert(
        tenant="niger", alert_type="conflict", severity="medium",
        status="resolved",
        zone_name="Lapai outskirts",
        lga="Lapai", lon=6.5667, lat=9.0333,
        confidence_score=0.76,
        affected_area_ha=31.0, livelihoods_at_risk=140,
        economic_value_ngn=4_500_000, predicted_breach_hours=None,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=52.0, human_review_required=False,
        agencies_notified=("Niger State SEMA",),
    ),

    # ── Zamfara (4 more — banditry / mining corridor) ────────────────────
    SeedAlert(
        tenant="zamfara", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Maru mining-edge farms",
        lga="Maru", lon=6.4, lat=12.3333,
        confidence_score=0.93,
        affected_area_ha=138.0, livelihoods_at_risk=650,
        economic_value_ngn=28_700_000, predicted_breach_hours=6,
        satellite_source="Copernicus Sentinel-1 SAR + heat",
        hours_ago=0.8, human_review_required=False,
        agencies_notified=("NEMA", "Zamfara MoAH", "Min. Agriculture"),
    ),
    SeedAlert(
        tenant="zamfara", alert_type="conflict", severity="critical",
        status="acknowledged",
        zone_name="Maradun banditry corridor",
        lga="Maradun", lon=6.1167, lat=12.5,
        confidence_score=0.90,
        affected_area_ha=98.0, livelihoods_at_risk=460,
        economic_value_ngn=20_400_000, predicted_breach_hours=10,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=3.2, human_review_required=False,
        agencies_notified=("NEMA", "Zamfara MoAH"),
    ),
    SeedAlert(
        tenant="zamfara", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Tsafe sorghum plots",
        lga="Tsafe", lon=6.95, lat=11.95,
        confidence_score=0.85,
        affected_area_ha=62.0, livelihoods_at_risk=285,
        economic_value_ngn=11_300_000, predicted_breach_hours=18,
        satellite_source="Sentinel-2 MSI",
        hours_ago=6.8, human_review_required=False,
        agencies_notified=("Zamfara MoAH",),
    ),
    SeedAlert(
        tenant="zamfara", alert_type="conflict", severity="medium",
        status="pending_review",
        zone_name="Birnin Magaji northern farms",
        lga="Birnin Magaji", lon=6.1, lat=12.95,
        confidence_score=0.79,
        affected_area_ha=44.0, livelihoods_at_risk=200,
        economic_value_ngn=6_800_000, predicted_breach_hours=None,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=12.0, human_review_required=True,
        agencies_notified=("Zamfara MoAH",),
    ),

    # ── FCT (3 new conflict — rural peripheries) ────────────────────────
    SeedAlert(
        tenant="fct", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Bwari rural farmlands",
        lga="Bwari", lon=7.3833, lat=9.2767,
        confidence_score=0.85,
        affected_area_ha=58.0, livelihoods_at_risk=265,
        economic_value_ngn=11_400_000, predicted_breach_hours=18,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=2.4, human_review_required=False,
        agencies_notified=("FCT Agric. Dept.", "NEMA"),
    ),
    SeedAlert(
        tenant="fct", alert_type="conflict", severity="medium",
        status="acknowledged",
        zone_name="Kuje grazing-boundary plots",
        lga="Kuje", lon=7.2, lat=8.8833,
        confidence_score=0.80,
        affected_area_ha=41.0, livelihoods_at_risk=185,
        economic_value_ngn=6_900_000, predicted_breach_hours=28,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=8.0, human_review_required=False,
        agencies_notified=("FCT Agric. Dept.",),
    ),
    SeedAlert(
        tenant="fct", alert_type="conflict", severity="medium",
        status="resolved",
        zone_name="Abaji river farms",
        lga="Abaji", lon=6.9333, lat=8.4667,
        confidence_score=0.75,
        affected_area_ha=33.0, livelihoods_at_risk=150,
        economic_value_ngn=5_100_000, predicted_breach_hours=None,
        satellite_source="Sentinel-2 MSI",
        hours_ago=44.0, human_review_required=False,
        agencies_notified=("FCT Agric. Dept.",),
    ),

    # ── Ghana (3 new — Upper East / Bawku belt) ─────────────────────────
    SeedAlert(
        tenant="ghana", alert_type="conflict", severity="critical",
        status="pending_review",
        zone_name="Pusiga border farms",
        lga="Pusiga", lon=-0.0833, lat=11.05,
        confidence_score=0.91,
        affected_area_ha=82.0, livelihoods_at_risk=380,
        economic_value_ngn=0.0,
        predicted_breach_hours=9,
        satellite_source="Copernicus Sentinel-1 SAR + heat",
        hours_ago=1.0, human_review_required=False,
        agencies_notified=("Ghana NADMO", "Min. of Food & Agric."),
    ),
    SeedAlert(
        tenant="ghana", alert_type="conflict", severity="high",
        status="acknowledged",
        zone_name="Garu-Tempane sorghum belt",
        lga="Garu-Tempane", lon=-0.1833, lat=10.9,
        confidence_score=0.86,
        affected_area_ha=64.0, livelihoods_at_risk=290,
        economic_value_ngn=0.0,
        predicted_breach_hours=24,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=4.5, human_review_required=False,
        agencies_notified=("Ghana NADMO",),
    ),
    SeedAlert(
        tenant="ghana", alert_type="conflict", severity="medium",
        status="pending_review",
        zone_name="Binduri millet farms",
        lga="Binduri", lon=-0.4167, lat=10.95,
        confidence_score=0.78,
        affected_area_ha=38.0, livelihoods_at_risk=170,
        economic_value_ngn=0.0,
        predicted_breach_hours=None,
        satellite_source="Sentinel-2 MSI NDVI",
        hours_ago=10.0, human_review_required=True,
        agencies_notified=("Ghana NADMO",),
    ),

    # ── Senegal (3 new — Casamance + Kolda corridor) ────────────────────
    SeedAlert(
        tenant="senegal", alert_type="conflict", severity="high",
        status="pending_review",
        zone_name="Sédhiou groundnut belt",
        lga="Sédhiou", lon=-15.55, lat=12.7,
        confidence_score=0.86,
        affected_area_ha=72.0, livelihoods_at_risk=325,
        economic_value_ngn=0.0,
        predicted_breach_hours=20,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=2.6, human_review_required=False,
        agencies_notified=("ANACIM", "Direction de la Protection des Végétaux"),
    ),
    SeedAlert(
        tenant="senegal", alert_type="conflict", severity="high",
        status="acknowledged",
        zone_name="Kolda transhumance corridor",
        lga="Kolda", lon=-14.95, lat=12.9,
        confidence_score=0.84,
        affected_area_ha=58.0, livelihoods_at_risk=260,
        economic_value_ngn=0.0,
        predicted_breach_hours=30,
        satellite_source="Copernicus Sentinel-1 SAR",
        hours_ago=5.0, human_review_required=False,
        agencies_notified=("ANACIM",),
    ),
    SeedAlert(
        tenant="senegal", alert_type="conflict", severity="medium",
        status="pending_review",
        zone_name="Bignona Casamance farms",
        lga="Bignona", lon=-16.25, lat=12.8,
        confidence_score=0.79,
        affected_area_ha=44.0, livelihoods_at_risk=200,
        economic_value_ngn=0.0,
        predicted_breach_hours=None,
        satellite_source="Sentinel-2 MSI",
        hours_ago=13.0, human_review_required=True,
        agencies_notified=("ANACIM",),
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


async def _purge_firms_alerts(session_factory, tenant: str) -> int:
    """Soft-delete every alert_events row generated by the FIRMS pipeline.

    Returns the number of rows touched. Soft-delete (is_deleted = TRUE)
    preserves the audit trail; raw heat_signatures rows are untouched.
    """
    schema = f"tenant_{tenant}"
    async with session_factory() as session:
        await session.execute(text(f"SET search_path TO {schema}, public"))
        result = await session.execute(
            text(
                "UPDATE alert_events SET is_deleted = TRUE "
                "WHERE model_name = :n AND NOT is_deleted"
            ),
            {"n": FIRMS_MODEL_NAME},
        )
        await session.commit()
        return result.rowcount or 0


async def main(*, purge_firms: bool = False) -> None:
    session_factory = get_session_factory()

    by_tenant: dict[str, list[SeedAlert]] = {}
    for a in SEED_ALERTS:
        by_tenant.setdefault(a.tenant, []).append(a)

    if purge_firms:
        print("[purge] soft-deleting FIRMS-derived alerts across all tenants…")
        total = 0
        for tenant in sorted(by_tenant):
            n = await _purge_firms_alerts(session_factory, tenant)
            if n:
                print(f"  tenant_{tenant}: purged {n}")
                total += n
        print(f"[purge] done — {total} FIRMS alerts soft-deleted\n")

    for tenant, fixtures in by_tenant.items():
        await _seed_for_tenant(session_factory, tenant, fixtures)
        print(f"[seed] tenant_{tenant}: {len(fixtures)} alerts")

    await get_engine().dispose()
    print(f"\n[seed] done — {sum(len(v) for v in by_tenant.values())} alerts across "
          f"{len(by_tenant)} tenants")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--purge-firms",
        action="store_true",
        help="Also soft-delete every nasa_firms-generated alert before seeding.",
    )
    args = parser.parse_args()
    asyncio.run(main(purge_firms=args.purge_firms))
