"""Seed deterministic crop_predictions rows for all pilot tenants (demo data).

CropGuard (Module 04) normally fills crop_predictions one row at a time as
the ML service classifies uploaded leaf photos, so the table is empty until
someone uploads — the dashboard map starts blank. This seed writes a handful
of plausible ResNet-50 predictions per tenant at real LGA centroids (a
disease-heavy mix plus a couple of healthy fields) so the map, halos and
recent-feed render without a manual upload.

`prediction` is the disease-probability mass (high for diseased classes,
low for healthy ones); `confidence` is the top-1 class probability. top_k is
a small leaderboard of {class_name, probability}. Images are tagged
image_source='inline' with a synthetic sha256 — no real bytes are stored.

Idempotent: deletes prior rows where model_version='0.0.0-seed' before
inserting. Real inference rows (other model_versions) are untouched.

NEVER run against a non-dev DB.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import text  # noqa: E402

from db.engine import get_engine, get_session_factory  # noqa: E402
from services.lga_geo import LGA_CENTROIDS, centroid_for  # noqa: E402
from services.tenants import PILOT_TENANT_IDS, tenant_schema_name  # noqa: E402


MODEL_NAME = "crop_classifier"
SEED_VERSION = "0.0.0-seed"
PREDICTIONS_PER_TENANT = 5

# Mirror of ml.models.crop_classifier.CROP_CLASSES — inlined to avoid pulling
# the torch-heavy ML module into the API seed runtime.
CROP_CLASSES: tuple[str, ...] = (
    "cassava_healthy", "cassava_mosaic_disease", "cassava_brown_streak",
    "maize_healthy", "maize_streak_virus", "maize_northern_blight",
    "rice_healthy", "rice_blast", "tomato_healthy", "tomato_late_blight",
    "plantain_healthy", "plantain_black_sigatoka",
)

# What each tenant ACTUALLY cultivates, restricted to the 5 crops the
# classifier knows (cassava, maize, rice, tomato, plantain). Plantain +
# cassava are humid-zone crops, so the arid NW states (Kebbi, Zamfara) get
# cereals/irrigated crops only — never plantain. (The model can't represent
# millet/sorghum/wheat/yam, so those real staples are simply omitted rather
# than mislabelled.)
TENANT_CROPS: dict[str, list[str]] = {
    "kebbi":    ["rice", "maize", "tomato"],            # Sokoto-Rima rice belt; no plantain/cassava
    "benue":    ["cassava", "rice", "maize", "plantain"],  # food basket; plantain in humid south
    "plateau":  ["maize", "tomato", "rice"],            # Jos highlands — veg/tomato
    "kaduna":   ["maize", "cassava", "rice", "tomato"],
    "niger":    ["rice", "cassava", "maize"],
    "zamfara":  ["maize", "rice"],                       # semi-arid NW; no plantain/cassava
    "nasarawa": ["rice", "cassava", "maize"],
    "fct":      ["maize", "cassava", "tomato"],
    "ghana":    ["cassava", "plantain", "maize", "rice"],  # humid forest — plantain major
    "senegal":  ["rice", "maize", "cassava"],            # Casamance rice belt
}

# The diseased class for each crop (used for the high-severity halos).
_DISEASE_CLASS: dict[str, str] = {
    "cassava":  "cassava_mosaic_disease",
    "maize":    "maize_northern_blight",
    "rice":     "rice_blast",
    "tomato":   "tomato_late_blight",
    "plantain": "plantain_black_sigatoka",
}


def _classes_for(tenant_id: str, n: int) -> list[str]:
    """n predicted classes drawn only from crops the tenant actually grows.
    Mostly diseased (so halos fire) with roughly one healthy field."""
    crops = TENANT_CROPS.get(tenant_id, ["maize", "rice"])
    out: list[str] = []
    for i in range(n):
        crop = crops[i % len(crops)]
        out.append(f"{crop}_healthy" if i % 4 == 3 else _DISEASE_CLASS[crop])
    return out


def _hash_unit(*parts: str) -> float:
    """Deterministic [0, 1) draw from the joined parts."""
    h = hashlib.md5("|".join(parts).encode(), usedforsecurity=False).digest()[:4]
    return int.from_bytes(h, "big") / 0xFFFFFFFF


def _band(confidence: float) -> str:
    if confidence >= 0.90:
        return "HIGH"
    if confidence >= 0.75:
        return "MEDIUM"
    return "LOW"


@dataclass(frozen=True, slots=True)
class CropSeed:
    predicted_class: str
    prediction: float
    confidence: float
    confidence_band: str
    top_k: list[dict[str, float | str]]
    lga: str
    lon: float
    lat: float
    inference_time_ms: int
    image_sha256: str


def _top_k_for(predicted_class: str, confidence: float, seed: str) -> list[dict[str, float | str]]:
    """Top-1 = predicted class; two deterministic runner-ups below it."""
    others = [c for c in CROP_CLASSES if c != predicted_class]
    i = int(_hash_unit(seed, "r") * len(others))
    r1, r2 = others[i % len(others)], others[(i + 1) % len(others)]
    residual = 1.0 - confidence
    return [
        {"class_name": predicted_class, "probability": round(confidence, 4)},
        {"class_name": r1, "probability": round(residual * 0.6, 4)},
        {"class_name": r2, "probability": round(residual * 0.25, 4)},
    ]


def _rows_for(tenant_id: str) -> list[CropSeed]:
    lgas = list(LGA_CENTROIDS.get(tenant_id, {}).keys())[:PREDICTIONS_PER_TENANT]
    classes = _classes_for(tenant_id, len(lgas))
    rows: list[CropSeed] = []
    for i, lga in enumerate(lgas):
        lon, lat = centroid_for(tenant_id, lga)
        predicted_class = classes[i]
        healthy = predicted_class.endswith("_healthy")
        seed = f"{tenant_id}|{lga}"
        if healthy:
            prediction = round(0.05 + _hash_unit(seed, "dis") * 0.18, 4)
            confidence = round(0.80 + _hash_unit(seed, "conf") * 0.15, 4)
        else:
            prediction = round(0.80 + _hash_unit(seed, "dis") * 0.15, 4)
            confidence = round(0.72 + _hash_unit(seed, "conf") * 0.23, 4)
        rows.append(CropSeed(
            predicted_class=predicted_class,
            prediction=prediction,
            confidence=confidence,
            confidence_band=_band(confidence),
            top_k=_top_k_for(predicted_class, confidence, seed),
            lga=lga,
            lon=lon,
            lat=lat,
            inference_time_ms=40 + int(_hash_unit(seed, "ms") * 80),
            image_sha256=hashlib.sha256(seed.encode()).hexdigest(),
        ))
    return rows


_INSERT_SQL = text(
    """
    INSERT INTO crop_predictions (
        tenant_id, model_name, model_version, input_hash,
        prediction, confidence, confidence_band, requires_human_review,
        predicted_class, top_k, image_source, image_sha256,
        location, lga, zone_name, inference_time_ms
    ) VALUES (
        :tenant_id, :model_name, :model_version, :input_hash,
        :prediction, :confidence, :confidence_band, :requires_human_review,
        :predicted_class, CAST(:top_k AS JSONB), 'inline', :image_sha256,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :lga, :zone_name, :inference_time_ms
    )
    """
)


async def seed() -> int:
    factory = get_session_factory()
    total = 0
    async with factory() as session:
        for tenant_id in sorted(PILOT_TENANT_IDS):
            schema = tenant_schema_name(tenant_id)
            await session.execute(text(f"SET search_path TO {schema}, public"))
            await session.execute(
                text("DELETE FROM crop_predictions WHERE model_version = :v"),
                {"v": SEED_VERSION},
            )
            for r in _rows_for(tenant_id):
                await session.execute(
                    _INSERT_SQL,
                    {
                        "tenant_id": tenant_id,
                        "model_name": MODEL_NAME,
                        "model_version": SEED_VERSION,
                        "input_hash": r.image_sha256,
                        "prediction": r.prediction,
                        "confidence": r.confidence,
                        "confidence_band": r.confidence_band,
                        "requires_human_review": r.confidence_band != "HIGH",
                        "predicted_class": r.predicted_class,
                        "top_k": json.dumps(r.top_k),
                        "image_sha256": r.image_sha256,
                        "lon": r.lon,
                        "lat": r.lat,
                        "lga": r.lga,
                        "zone_name": r.lga,
                        "inference_time_ms": r.inference_time_ms,
                    },
                )
                total += 1
        await session.commit()
    return total


async def main() -> None:
    n = await seed()
    print(f"seeded {n} crop_predictions rows (model_version={SEED_VERSION})")
    engine = get_engine()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
