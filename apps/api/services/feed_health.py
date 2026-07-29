"""Feed health — the watchdog that did not exist.

WHY THIS FILE EXISTS
--------------------
On 2026-07-28 we found that an exhausted Copernicus quota had been causing the
encroachment sweep to DELETE each scanned LGA's real NDVI and write NULL in its
place. It had run daily for about sixteen days. In that time it wiped 306 of
447 crop_health rows and left one tenant with none at all.

Every signal said the system was fine. `ingestion_runs` recorded `succeeded`.
The dashboard showed a recent scan. Nothing was red, because nothing was
looking. It was found by hand, by noticing that two log lines disagreed.

So the lesson is not "fix that bug" — that is done. It is that we had no way to
learn about a silent failure except for someone to go looking. This module is
that way.

WHAT IT CHECKS
--------------
Two questions, deliberately different in kind:

1. STALENESS — has each feed succeeded recently enough for its own cadence?
   Catches a feed that stopped, crashed, or now records `failed`. This is the
   easy half, and on its own it would NOT have caught the incident above,
   because those runs reported success.

2. REGRESSION — is a table's stock of REAL data going backwards?
   This is the half that matters. A feed that runs, reports success, and
   quietly destroys what it already had is invisible to any status check.
   Counting real rows over time makes it visible: data should grow or hold, and
   a fall is either a deliberate purge or a bug, both of which a human should
   see. Baselines live in public.feed_health_marks.

A check that only ever confirmed things were fine would be worse than none, so
each probe states what it measured, not merely pass/fail.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Feeds that stamp public.ingestion_runs, and how long each may go without a
# SUCCESS before we call it stale. Generous multiples of the real cadence — a
# daily feed missing one run is weather, missing three days is a fault.
#
# THESE KEYS MUST BE THE STRINGS THE TASKS ACTUALLY WRITE, not the module names.
# On its very first production run this list said `firms_ingest_v1` and the
# watchdog reported "has NEVER recorded a successful run" — for a feed sitting
# on 450 runs, 448 successful. The task writes `MODIS_NRT`. A watchdog whose
# opening move is a false alarm gets muted, and a muted watchdog is the same as
# no watchdog, so `_check_unmonitored` below now makes that mistake
# self-reporting rather than trusting anyone to keep this list honest.
FEED_MAX_AGE_HOURS: dict[str, int] = {
    "encroachment_detector_v1": 72,     # daily 07:00
    "shockguard_scan_v1": 72,           # daily 07:30
    "rainstorm_scan_v1": 72,            # daily 08:00
    "MODIS_NRT": 72,                    # daily 06:00 — NASA FIRMS fire ingest
    "conflict_pipeline_v1": 72,         # daily 06:30
    "food_prices_v1": 24 * 45,          # monthly on the 5th
}

# Tables whose REAL row count must not fall. `real_predicate` is the SQL that
# distinguishes a genuine reading from a placeholder — the whole point is to
# count what we actually know, so a table refilled with NULLs still trips.
#
# `scope` matters: crop_prices lives in PUBLIC, not per-tenant, so probing it
# once per tenant reported the same 456 ten times. Ten identical lines are not
# ten checks, they are padding that buries the real ones.
@dataclass(frozen=True)
class StockProbe:
    key: str
    table: str
    real_predicate: str
    note: str
    scope: str = "tenant"          # 'tenant' | 'global'


STOCK_PROBES: tuple[StockProbe, ...] = (
    StockProbe(
        key="crop_health_real_ndvi",
        table="crop_health",
        real_predicate="ndvi IS NOT NULL",
        note="per-LGA Sentinel-2 NDVI — the exact stock the 2026-07 incident ate",
    ),
    # NO PROBE ON shock_events. Removed 2026-07-29 after it produced this
    # watchdog's first alert, and that alert was wrong:
    #
    #   [CRITICAL] senegal/shock_events_live  real rows fell 2 -> 0
    #
    # Senegal's two rows were gone because that morning's rainfall scan RAN
    # SUCCESSFULLY and correctly found no exceptional rainfall there — while
    # kaduna gained 3, nasarawa 2 and plateau 5 in the same run. Both live
    # detectors replace their rows every run (`_replace_prior`), so their count
    # tracks CURRENT WEATHER, not accumulated knowledge. It is supposed to rise
    # and fall, and zero is a normal, correct, frequent answer.
    #
    # A stock probe on a self-replacing feed is therefore guaranteed to cry wolf
    # on the first quiet day — and a watchdog people learn to ignore is worse
    # than no watchdog, which is the one thing this module cannot afford.
    #
    # Health of these feeds is already covered, correctly, by the staleness
    # check: "rainstorm_scan_v1: last success 1h ago". If a detector dies, that
    # is what notices. Row count adds no signal a human should be woken for.
    StockProbe(
        key="crop_prices_real",
        table="crop_prices",
        real_predicate="COALESCE(source, '') <> 'seed_v1'",
        note="ingested market prices, seeds excluded",
        scope="global",
    ),
)

# Tenant id used for global-scope marks, so they cannot collide with a real one.
GLOBAL_SCOPE = "_global"

# A stock may dip slightly for legitimate reasons (an LGA genuinely clearing its
# watch, a month rolling out of a window). Only a fall beyond this fraction is
# reported, so the check stays quiet unless something real happened.
STOCK_DROP_TOLERANCE = 0.10


@dataclass
class Finding:
    severity: str          # 'critical' | 'warning'
    subject: str
    detail: str


@dataclass
class HealthReport:
    checked_at: datetime
    findings: list[Finding] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.findings

    def summary(self) -> str:
        if self.healthy:
            return f"all feeds healthy ({len(self.observations)} probes)"
        crit = sum(1 for f in self.findings if f.severity == "critical")
        return (
            f"{len(self.findings)} finding(s), {crit} critical — "
            + "; ".join(f"{f.subject}: {f.detail}" for f in self.findings[:4])
        )


async def _check_staleness(
    session: AsyncSession, report: HealthReport, now: datetime,
) -> None:
    rows = (await session.execute(text(
        "SELECT source, MAX(finished_at) FILTER (WHERE status = 'succeeded') AS ok_at, "
        "       MAX(finished_at) AS any_at "
        "  FROM public.ingestion_runs GROUP BY source"
    ))).all()
    seen = {r[0]: (r[1], r[2]) for r in rows}

    for source, max_age_h in FEED_MAX_AGE_HOURS.items():
        ok_at, any_at = seen.get(source, (None, None))
        if ok_at is None:
            report.findings.append(Finding(
                "critical", source,
                "has NEVER recorded a successful run"
                + (f" (last attempt {any_at:%Y-%m-%d %H:%M} UTC)" if any_at else ""),
            ))
            continue
        age_h = (now - ok_at).total_seconds() / 3600.0
        if age_h > max_age_h:
            report.findings.append(Finding(
                "critical" if age_h > max_age_h * 2 else "warning", source,
                f"last success {age_h:.0f}h ago ({ok_at:%Y-%m-%d %H:%M} UTC), "
                f"tolerance {max_age_h}h",
            ))
        else:
            report.observations.append(
                f"{source}: last success {age_h:.0f}h ago"
            )

    _check_unmonitored(report, set(seen))


def _check_unmonitored(report: HealthReport, live_sources: set[str]) -> None:
    """Report feeds that write runs but that nothing above is watching.

    The inverse blind spot, and the one that let the FIRMS mistake happen: a
    budget keyed on a source string nobody writes watches nothing, silently and
    for as long as the typo survives. Anything stamping ingestion_runs without
    an entry in FEED_MAX_AGE_HOURS is therefore itself a finding — either the
    budget needs the name, or the source is stray and should stop writing.

    A warning rather than critical: an unwatched feed is a gap in our knowledge,
    not evidence that anything is broken.
    """
    unknown = sorted(live_sources - set(FEED_MAX_AGE_HOURS))
    for source in unknown:
        report.findings.append(Finding(
            "warning", source,
            "writes to ingestion_runs but has no staleness budget — nothing is "
            "watching it. Add it to FEED_MAX_AGE_HOURS or stop it writing.",
        ))


async def _check_stock(
    session: AsyncSession, report: HealthReport, tenant: str, now: datetime,
    *, scope: str = "tenant",
) -> None:
    """Compare each probe's real-row count against its last recorded mark."""
    for probe in STOCK_PROBES:
        if probe.scope != scope:
            continue
        try:
            current = (await session.execute(text(
                f"SELECT count(*) FROM {probe.table} WHERE {probe.real_predicate}"
            ))).scalar_one()
        except Exception as exc:                       # noqa: BLE001
            # A missing table is a deployment state, not a data fault. Say so
            # rather than failing the whole check.
            await session.rollback()
            report.observations.append(f"{tenant}/{probe.key}: unreadable ({exc})")
            continue

        prev = (await session.execute(text(
            "SELECT value, recorded_at FROM public.feed_health_marks "
            " WHERE tenant_id = :t AND probe = :p"
        ), {"t": tenant, "p": probe.key})).first()

        if prev is not None:
            before, when = int(prev[0]), prev[1]
            if before > 0 and current < before * (1 - STOCK_DROP_TOLERANCE):
                report.findings.append(Finding(
                    "critical", f"{tenant}/{probe.key}",
                    f"real rows fell {before} -> {current} since "
                    f"{when:%Y-%m-%d %H:%M} UTC ({probe.note}). Data is being "
                    "destroyed or a source stopped qualifying as real.",
                ))
            else:
                report.observations.append(
                    f"{tenant}/{probe.key}: {current} (was {before})"
                )
        else:
            report.observations.append(f"{tenant}/{probe.key}: {current} (first mark)")

        await session.execute(text(
            "INSERT INTO public.feed_health_marks (tenant_id, probe, value, recorded_at) "
            "VALUES (:t, :p, :v, :now) "
            "ON CONFLICT (tenant_id, probe) DO UPDATE "
            "   SET value = EXCLUDED.value, recorded_at = EXCLUDED.recorded_at"
        ), {"t": tenant, "p": probe.key, "v": current, "now": now})


async def run_health_check(
    session: AsyncSession, tenants: list[str], *, now: datetime | None = None,
) -> HealthReport:
    """Full sweep. Records new stock marks as a side effect; caller commits."""
    now = now or datetime.now(timezone.utc)
    report = HealthReport(checked_at=now)

    await _check_staleness(session, report, now)

    from services.tenants import tenant_schema_name

    for tenant in tenants:
        await session.execute(
            text(f"SET search_path TO {tenant_schema_name(tenant)}, public")
        )
        await _check_stock(session, report, tenant, now, scope="tenant")

    # Shared tables get exactly one probe. Running them per tenant reported the
    # same number ten times, which reads as ten checks and is one.
    await session.execute(text("SET search_path TO public"))
    await _check_stock(session, report, GLOBAL_SCOPE, now, scope="global")

    return report


def format_email(report: HealthReport) -> tuple[str, str]:
    """Subject + plain-text body for an unhealthy report."""
    crit = sum(1 for f in report.findings if f.severity == "critical")
    subject = (
        f"[EconomicBridge] feed health: {len(report.findings)} finding(s)"
        + (f", {crit} critical" if crit else "")
    )
    lines = [
        f"Feed health check at {report.checked_at:%Y-%m-%d %H:%M} UTC.",
        "",
        "FINDINGS",
        "--------",
    ]
    for f in report.findings:
        lines.append(f"[{f.severity.upper()}] {f.subject}")
        lines.append(f"    {f.detail}")
    lines += [
        "",
        "WHAT WAS ALSO MEASURED (no action needed)",
        "-----------------------------------------",
    ]
    lines += [f"  {o}" for o in report.observations]
    lines += [
        "",
        "This check exists because a bug once deleted real satellite readings",
        "daily for sixteen days while every status said 'succeeded'.",
        "",
        "— EconomicBridge (operated by Bizra Farms Integrated Nigeria Ltd)",
    ]
    return subject, "\n".join(lines)
