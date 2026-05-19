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

Pass-driven Copernicus ingestion (Sentinel-1/2 wakeup ~10 min before
each predicted N2YO pass) arrives in Phase A.6 once A.3 unblocks.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from db import PILOT_TENANT_IDS, get_session_factory
from tasks.firms_ingest import ingest_firms_for_tenant

log = logging.getLogger(__name__)


# Job IDs — exposed so the introspection endpoint + tests can reference them.
JOB_ID_FIRMS_DAILY = "firms_daily_06utc"


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
