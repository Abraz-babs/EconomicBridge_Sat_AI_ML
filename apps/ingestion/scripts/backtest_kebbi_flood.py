"""Retrospective flood backtest — Kebbi, 2024 (proof-of-detection asset).

Runs the SAME method the live ShockGuard detector uses — Sentinel-1 SAR VV(dB)
backscatter drop via the platform's CDSE Statistical client, scored by the exact
`compute_shock` logic — pointed at the Sept-2024 Kebbi flood window, per LGA.
The point: show the platform detects a documented disaster, verified against the
public record (the 11 river LGAs NEMA/state named), from orbit, no field visit.

The 21 Kebbi LGAs are the accuracy test: the 11 low-lying river LGAs should flag
(flood), the ~10 upland LGAs should stay quiet.

READY TO RUN when the CDSE monthly-quota breaker resets (~1st of the month).
While the breaker is open every call returns empty — expected; run after reset,
where CDSE creds are set (local .env, or a one-shot ECS task on the ingestion
service, like the restore drill).

    apps/api/.venv/Scripts/python.exe apps/ingestion/scripts/backtest_kebbi_flood.py
"""
from __future__ import annotations

import asyncio
import json
import math
import pathlib
import sys
from datetime import datetime, timezone
from statistics import mean, pstdev

ING = pathlib.Path(__file__).resolve().parents[1]  # apps/ingestion
sys.path.insert(0, str(ING))

from sources.copernicus import CopernicusClient  # noqa: E402
from sources.sentinel_statistical import (  # noqa: E402
    EVALSCRIPT_S1_VV_DB,
    SentinelStatisticalClient,
)

# ─── Flood detector — verbatim mirror of tasks/shockguard_scan.compute_shock ──
RECENT_N, MIN_POINTS, SAR_SCALE, THRESHOLD = 3, 6, 2.5, 0.55


def _severity(c: float) -> str:
    return "critical" if c >= 0.82 else "high" if c >= 0.68 else "medium"


def compute_flood(vals: list[float]) -> dict | None:
    """A DROP in SAR backscatter = open water = flood (mirrors the live scan)."""
    if len(vals) < MIN_POINTS:
        return None
    base, recent = vals[:-RECENT_N], vals[-RECENT_N:]
    std = pstdev(base) or 1e-6
    z = (mean(recent) - mean(base)) / std       # negative = drop
    drop = max(0.0, -z)
    c = math.tanh(drop / SAR_SCALE)
    if c < THRESHOLD:
        return None
    return {"z": round(z, 3), "confidence": round(c, 4), "severity": _severity(c)}


def bbox_around(lat: float, lon: float, half_m: float = 1500.0):
    """~3 km box around an LGA centroid — matches the per-LGA live scan footprint."""
    dlat = half_m / 111320.0
    dlon = half_m / (111320.0 * math.cos(math.radians(lat)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


RES_DEG = 0.0016  # ~180 m grid over the box; low PU, consistent across passes

# ─── 2024 Kebbi flood window: baseline early, flood peak in the "recent" points ──
# Peaked ~mid-late September 2024. End near the peak so compute_shock's last-3
# "recent" acquisitions fall inside the flood. Tune WIN_END to the peak on run day.
WIN_START = datetime(2024, 6, 10, tzinfo=timezone.utc)
WIN_END = datetime(2024, 10, 1, tzinfo=timezone.utc)

# Ground truth — the 11 LGAs the public record names as flood-hit (2022 & 2024).
# Names matched to lga_centroids.json spellings (Bagudu, Koko-Besse, Dandi).
KNOWN_FLOODED = {
    "Argungu", "Birnin Kebbi", "Bunza", "Suru", "Koko-Besse", "Yauri",
    "Shanga", "Bagudu", "Maiyama", "Jega", "Dandi",
}

CENTROIDS = json.loads((ING / "data" / "lga_centroids.json").read_text(encoding="utf-8"))
OUT = pathlib.Path(__file__).resolve().parents[3] / "scratchpad" / "kebbi_flood_backtest.json"


async def main() -> None:
    client = SentinelStatisticalClient(CopernicusClient())
    if not client.configured:
        print("CDSE creds not configured — set COPERNICUS_* and re-run where creds exist.")
        return

    rows: list[dict] = []
    for g in CENTROIDS["kebbi"]:
        try:
            pts = await client.compute_time_series(
                bbox=bbox_around(g["lat"], g["lon"]),
                start=WIN_START, end=WIN_END,
                dataset="sentinel-1-grd", evalscript=EVALSCRIPT_S1_VV_DB,
                resolution_deg=RES_DEG,
            )
        except Exception as exc:  # noqa: BLE001 — log per LGA, keep going
            print(f"{g['lga']:16s} ERROR {exc}")
            continue
        series = [(p.interval_from.date().isoformat(), round(p.mean, 2))
                  for p in pts if p.mean is not None]
        sig = compute_flood([v for _, v in series])
        known = g["lga"] in KNOWN_FLOODED
        rows.append({
            "lga": g["lga"], "n_obs": len(series), "flagged": bool(sig),
            **(sig or {"z": None, "confidence": None, "severity": None}),
            "known_flooded": known, "series": series,
        })
        tag = "  <- record: flooded" if known else ""
        print(f"{g['lga']:16s} n={len(series):2d} flagged={str(bool(sig)):5s} "
              f"z={sig['z'] if sig else '-'} conf={sig['confidence'] if sig else '-'}{tag}")

    flagged = {r["lga"] for r in rows if r["flagged"]}
    known = {r["lga"] for r in rows if r["known_flooded"]}
    if not any(r["n_obs"] for r in rows):
        print("\nNo observations returned — the CDSE monthly-quota breaker is likely still "
              "open. Re-run after the reset.")

    print("\n=== BACKTEST SUMMARY — Kebbi, Sept-2024 flood window ===")
    print(f"LGAs scanned {len(rows)} | flagged {len(flagged)} | ground-truth flooded {len(known)}")
    print(f"Detected AND in record : {len(flagged & known)}/{len(known)}  {sorted(flagged & known)}")
    print(f"Missed (record not flagged): {sorted(known - flagged)}")
    print(f"Flagged beyond the record  : {sorted(flagged - known)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "event": "Kebbi State flood, September 2024",
        "window": [WIN_START.date().isoformat(), WIN_END.date().isoformat()],
        "method": "Sentinel-1 SAR VV(dB) backscatter-drop z-score (compute_shock, SAR_SCALE=2.5, threshold=0.55)",
        "known_flooded": sorted(known),
        "detected": sorted(flagged),
        "rows": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nsaved {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
