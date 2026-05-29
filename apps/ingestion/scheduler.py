"""In-process APScheduler wiring for the ingestion service.

One async scheduler attached to the FastAPI lifespan. Jobs run inside
the same uvicorn process, sharing the DB pool. Trade-offs:

  + Zero infra: no Redis, no broker, no separate worker pod.
  + Easy to reason about — same logger, same async loop.
  - Single point of failure. If the uvicorn pod dies, jobs miss their
    fire time. Acceptable for staging; production should migrate to a
    Celery beat + workers split once we have multiple pods.

Schedule (mirrors CLAUDE.md §8):
  * NASA FIRMS — daily at 06:00 UTC for every active pilot tenant.
  * Conflict predictor — daily at 06:30 UTC, after FIRMS lands fresh
    heat_signatures.
  * Pass-driven imagery sweep (Slice 3c) — every 15 min, refreshes
    the CDSE STAC cache for tenants with a Sentinel-1/2 pass inside
    a ±20 min window. Saves CDSE QPS vs. polling blindly.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from db import PILOT_TENANT_IDS, get_session_factory
from sources.worldbank import TENANT_TO_ISO3
from tasks.aid_ingest import ingest_aid_for_tenant
from tasks.conflict_pipeline import run_daily_conflict_pipeline
from tasks.firms_ingest import ingest_firms_for_tenant
from tasks.mobility_ingest import ingest_mobility_worldbank_for_tenant
from tasks.pass_imagery_sweep import run_pass_imagery_sweep
from tasks.worldpop_raster_sample import sweep_tenant as worldpop_sweep_tenant

log = logging.getLogger(__name__)


# Job IDs — exposed so the introspection endpoint + tests can reference them.
JOB_ID_FIRMS_DAILY = "firms_daily_06utc"
JOB_ID_CONFLICT_DAILY = "conflict_daily_0630utc"
JOB_ID_PASS_IMAGERY_SWEEP = "pass_imagery_sweep_15min"
JOB_ID_WORLDPOP_WEEKLY = "worldpop_weekly_sun_07utc"
JOB_ID_MOBILITY_MONTHLY = "mobility_worldbank_monthly_1st_08utc"
JOB_ID_AID_MONTHLY = "aid_hapi_monthly_1st_09utc"


def setup_scheduler() -> AsyncIOScheduler:
    """Build (but do not start) the configured scheduler.

    Callers start it during FastAPI lifespan setup and shut it down on
    teardown. Keeping construction separate makes the scheduler testable.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        run_daily_firms_ingest,
        trigger=CronTrigger(hour=6, minute=0, timezone="UTC"),
        id=JOB_ID_FIRMS_DAILY,
        name="NASA FIRMS daily ingest (all pilot tenants)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,  # if we missed the 06:00 fire by <1h, still run
    )

    scheduler.add_job(
        run_daily_conflict_pipeline,
        # Fire 30min after FIRMS so the freshest heat_signatures feed the
        # conflict feature extractor.
        trigger=CronTrigger(hour=6, minute=30, timezone="UTC"),
        id=JOB_ID_CONFLICT_DAILY,
        name="Conflict predictor daily sweep (all pilot tenants)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        run_pass_imagery_sweep,
        trigger=IntervalTrigger(minutes=15),
        id=JOB_ID_PASS_IMAGERY_SWEEP,
        name="Pass-driven CDSE refresh (Sentinel-1/2 around N2YO passes)",
        replace_existing=True,
        max_instances=1,
        # 5 min grace: if we missed a tick the next one runs anyway, no
        # point in piling up replays.
        misfire_grace_time=300,
    )

    scheduler.add_job(
        run_weekly_worldpop_sweep,
        # WorldPop publishes annual rasters; weekly is plenty. Sunday
        # 07:00 UTC lands after Saturday-night FIRMS + conflict pipeline.
        trigger=CronTrigger(day_of_week="sun", hour=7, minute=0, timezone="UTC"),
        id=JOB_ID_WORLDPOP_WEEKLY,
        name="WorldPop COG sweep (all pilot tenants, weekly)",
        replace_existing=True,
        max_instances=1,
        # 6h grace covers a Sunday-morning pod restart.
        misfire_grace_time=21600,
    )

    scheduler.add_job(
        run_monthly_mobility_ingest,
        # World Bank republishes national indicators on a slow cadence and
        # NBS CPI is monthly — the 1st at 08:00 UTC is plenty.
        trigger=CronTrigger(day=1, hour=8, minute=0, timezone="UTC"),
        id=JOB_ID_MOBILITY_MONTHLY,
        name="World Bank mobility income anchor (Nigerian pilots, monthly)",
        replace_existing=True,
        max_instances=1,
        # 12h grace covers a pod restart on the 1st.
        misfire_grace_time=43200,
    )

    scheduler.add_job(
        run_monthly_aid_ingest,
        # HAPI operational-presence refreshes on a slow (~monthly) cadence;
        # 09:00 UTC on the 1st, after the mobility anchor.
        trigger=CronTrigger(day=1, hour=9, minute=0, timezone="UTC"),
        id=JOB_ID_AID_MONTHLY,
        name="HDX HAPI aid-coordination coverage (all pilots, monthly)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=43200,
    )

    return scheduler


async def run_daily_firms_ingest(
    tenants: Iterable[str] | None = None,
) -> dict[str, int | str]:
    """Pull FIRMS detections + promote to alert_events for every tenant.

    Used as both the cron callback and the body of an admin-trigger
    endpoint (when we add one). Returns a per-tenant count summary so
    callers can log / report.

    Failures for one tenant do not abort the rest — we log and continue.
    """
    target_tenants = list(tenants) if tenants is not None else sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    results: dict[str, int | str] = {}

    for tenant_id in target_tenants:
        async with factory() as session:
            try:
                result = await ingest_firms_for_tenant(
                    session,
                    tenant_id=tenant_id,
                    generate_alerts=True,
                    trigger="scheduled",
                )
                results[tenant_id] = result.records_ingested
                log.info(
                    "scheduled.firms tenant=%s records=%d alerts_inserted=%s",
                    tenant_id,
                    result.records_ingested,
                    result.alerts.inserted if result.alerts else "n/a",
                )
            except Exception as exc:  # noqa: BLE001 — we want every failure logged
                results[tenant_id] = f"failed: {exc!s}"
                log.exception(
                    "scheduled.firms FAILED tenant=%s: %s", tenant_id, exc
                )

    log.info("scheduled.firms summary: %s", results)
    return results


async def run_weekly_worldpop_sweep(
    tenants: Iterable[str] | None = None,
) -> dict[str, str]:
    """Sample WorldPop COGs at every poverty_villages row for every tenant.

    Sequential per-tenant — never hammer WorldPop's CDN with parallel
    requests. Failures for one tenant do not abort the rest.
    """
    target = list(tenants) if tenants is not None else sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    results: dict[str, str] = {}

    for tenant_id in target:
        async with factory() as session:
            try:
                outcome = await worldpop_sweep_tenant(session, tenant_id)
                if outcome.failed:
                    results[tenant_id] = f"failed: {outcome.error}"
                else:
                    results[tenant_id] = (
                        f"{outcome.valid}/{outcome.requested} valid, "
                        f"{outcome.nodata} nodata"
                    )
                log.info(
                    "scheduled.worldpop tenant=%s outcome=%s",
                    tenant_id, results[tenant_id],
                )
            except Exception as exc:  # noqa: BLE001
                results[tenant_id] = f"failed: {exc!s}"
                log.exception(
                    "scheduled.worldpop FAILED tenant=%s: %s", tenant_id, exc
                )

    log.info("scheduled.worldpop summary: %s", results)
    return results


async def run_monthly_mobility_ingest(
    tenants: Iterable[str] | None = None,
) -> dict[str, str]:
    """Anchor Module 06 to the World Bank national income figure, monthly.

    Covers all pilots — USD is the universal anchor (no FX), so Ghana/Senegal
    are included alongside the Nigerian states. Pulls keylessly from the
    World Bank API; failures for one tenant don't abort the rest.
    """
    if tenants is not None:
        target = list(tenants)
    else:
        target = [t for t in sorted(PILOT_TENANT_IDS) if TENANT_TO_ISO3.get(t) is not None]
    factory = get_session_factory()
    results: dict[str, str] = {}

    for tenant_id in target:
        async with factory() as session:
            try:
                outcome = await ingest_mobility_worldbank_for_tenant(
                    session, tenant_id=tenant_id,
                )
                results[tenant_id] = f"{outcome.rows_upserted}/{outcome.lgas_found} upserted"
                log.info(
                    "scheduled.mobility tenant=%s outcome=%s",
                    tenant_id, results[tenant_id],
                )
            except Exception as exc:  # noqa: BLE001 — log every failure, continue
                results[tenant_id] = f"failed: {exc!s}"
                log.exception(
                    "scheduled.mobility FAILED tenant=%s: %s", tenant_id, exc
                )

    log.info("scheduled.mobility summary: %s", results)
    return results


async def run_monthly_aid_ingest(
    tenants: Iterable[str] | None = None,
) -> dict[str, str]:
    """Refresh Module 02 aid coverage from HDX HAPI for every pilot, monthly.

    Keyless. Failures for one tenant don't abort the rest. Tenants with no
    humanitarian operational presence simply write nothing (seed remains).
    """
    target = list(tenants) if tenants is not None else sorted(PILOT_TENANT_IDS)
    factory = get_session_factory()
    results: dict[str, str] = {}

    for tenant_id in target:
        async with factory() as session:
            try:
                outcome = await ingest_aid_for_tenant(session, tenant_id=tenant_id)
                results[tenant_id] = (
                    f"{outcome.coverage_rows} rows, {outcome.lgas_covered} LGAs, "
                    f"{outcome.orgs_found} orgs"
                )
                log.info("scheduled.aid tenant=%s outcome=%s", tenant_id, results[tenant_id])
            except Exception as exc:  # noqa: BLE001 — log every failure, continue
                results[tenant_id] = f"failed: {exc!s}"
                log.exception("scheduled.aid FAILED tenant=%s: %s", tenant_id, exc)

    log.info("scheduled.aid summary: %s", results)
    return results
