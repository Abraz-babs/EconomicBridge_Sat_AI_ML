"""GET /api/v1/scheduler/jobs — introspect the in-process scheduler.

Read-only listing of jobs registered with the APScheduler instance
attached to `app.state` during lifespan startup. Useful both as a
health check (is the scheduler running?) and as a quick sanity check
for the cron expressions during deployment.

Also exposes:
  - POST /api/v1/scheduler/jobs/{job_id}/run — manually fire a registered
    job's body. Useful for testing the cron-driven flow without waiting
    for 06:00 UTC.
  - GET  /api/v1/scheduler/runs/recent — the last N runs from
    `public.ingestion_runs`, so dashboards can show "FIRMS last ran
    23h ago, succeeded, 47 records" without scraping logs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from scheduler import (
    JOB_ID_AID_MONTHLY,
    JOB_ID_CONFLICT_DAILY,
    JOB_ID_FIRMS_DAILY,
    JOB_ID_MOBILITY_MONTHLY,
    JOB_ID_PASS_IMAGERY_SWEEP,
    JOB_ID_SATOBS_WEEKLY,
    JOB_ID_SKILLS_MONTHLY,
    JOB_ID_WORLDPOP_WEEKLY,
    run_daily_firms_ingest,
    run_monthly_aid_ingest,
    run_monthly_mobility_ingest,
    run_monthly_skills_ingest,
    run_weekly_satellite_observations,
    run_weekly_worldpop_sweep,
)
from tasks.conflict_pipeline import run_daily_conflict_pipeline
from tasks.pass_imagery_sweep import run_pass_imagery_sweep

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


class JobInfo(BaseModel):
    id: str
    name: str
    next_run_time: datetime | None
    trigger: str


class JobsListResponse(BaseModel):
    running: bool
    jobs: list[JobInfo]


@router.get(
    "/jobs",
    response_model=JobsListResponse,
    summary="List in-process scheduler jobs",
)
async def list_jobs(request: Request) -> JobsListResponse:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return JobsListResponse(running=False, jobs=[])
    return JobsListResponse(
        running=scheduler.running,
        jobs=[
            JobInfo(
                id=j.id,
                name=j.name or j.id,
                next_run_time=j.next_run_time,
                trigger=str(j.trigger),
            )
            for j in scheduler.get_jobs()
        ],
    )


# ─── Manual-trigger map ────────────────────────────────────────────────────
# Map of job_id -> async callable. Lets us fire a registered job's body
# directly. NOT the same as APScheduler's `modify_job(next_run_time=...)`
# (which would change the schedule); this just runs the work once.

_TRIGGERABLE_JOBS = {
    JOB_ID_FIRMS_DAILY: run_daily_firms_ingest,
    JOB_ID_CONFLICT_DAILY: run_daily_conflict_pipeline,
    JOB_ID_WORLDPOP_WEEKLY: run_weekly_worldpop_sweep,
    # Slices 21/22/26-33 jobs — every registered job is manually fireable, so
    # a fresh deployment can pull all live feeds immediately instead of
    # waiting for the weekly/monthly cron (Admin → Scheduler → Run now).
    JOB_ID_SATOBS_WEEKLY: run_weekly_satellite_observations,
    JOB_ID_MOBILITY_MONTHLY: run_monthly_mobility_ingest,
    JOB_ID_AID_MONTHLY: run_monthly_aid_ingest,
    JOB_ID_SKILLS_MONTHLY: run_monthly_skills_ingest,
    JOB_ID_PASS_IMAGERY_SWEEP: None,  # adapted below — returns a dataclass
}


async def _run_pass_sweep_as_dict() -> dict:
    """Adapter: run_pass_imagery_sweep returns a SweepResult dataclass; the
    response model wants a plain dict like every other job body."""
    res = await run_pass_imagery_sweep()
    return {
        "ran_at": res.ran_at.isoformat(),
        "decisions": len(res.decisions),
        "refreshed": res.refreshed_count,
    }


_TRIGGERABLE_JOBS[JOB_ID_PASS_IMAGERY_SWEEP] = _run_pass_sweep_as_dict


class JobRunResponse(BaseModel):
    job_id: str
    result: dict


@router.post(
    "/jobs/{job_id}/run",
    response_model=JobRunResponse,
    summary="Manually fire a scheduled job's body",
)
async def run_job_now(job_id: str) -> JobRunResponse:
    if job_id not in _TRIGGERABLE_JOBS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job_id: {job_id!r}. "
            f"Known: {sorted(_TRIGGERABLE_JOBS)}",
        )
    callback = _TRIGGERABLE_JOBS[job_id]
    result = await callback()
    return JobRunResponse(job_id=job_id, result=result)


# ─── GET /api/v1/scheduler/runs/recent — pipeline observability ───────────


class IngestionRunRow(BaseModel):
    """One row from `public.ingestion_runs`, projected to what dashboards
    actually display."""
    run_id: str
    tenant_id: str | None
    source: str
    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    records_ingested: int
    error_message: str | None


class RunsRecentResponse(BaseModel):
    rows: list[IngestionRunRow]
    total: int


@router.get(
    "/runs/recent",
    response_model=RunsRecentResponse,
    summary="Recent ingestion runs across all pipelines",
    description=(
        "Read-only projection of `public.ingestion_runs` so dashboards "
        "can show 'FIRMS last ran 23h ago, succeeded, 47 records' without "
        "scraping logs. Filter by tenant or source if needed."
    ),
)
async def list_recent_runs(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int, Query(ge=1, le=200, description="Max rows returned.")
    ] = 50,
    tenant_id: Annotated[
        str | None, Query(description="Filter to one tenant slug.")
    ] = None,
    source: Annotated[
        str | None, Query(description="Filter to one source (e.g. MODIS_NRT).")
    ] = None,
) -> RunsRecentResponse:
    where_clauses: list[str] = []
    params: dict[str, object] = {"limit": limit}
    if tenant_id:
        where_clauses.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id.strip().lower()
    if source:
        where_clauses.append("source = :source")
        params["source"] = source.strip()

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = text(
        f"""
        SELECT id::text AS run_id, tenant_id, source, status, trigger,
               started_at, finished_at,
               EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_seconds,
               records_ingested, error_message
          FROM public.ingestion_runs
          {where_sql}
         ORDER BY started_at DESC
         LIMIT :limit
        """
    )
    rows = (await session.execute(sql, params)).mappings().all()
    return RunsRecentResponse(
        rows=[
            IngestionRunRow(
                run_id=r["run_id"],
                tenant_id=r["tenant_id"],
                source=r["source"],
                status=r["status"],
                trigger=r["trigger"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                duration_seconds=(
                    float(r["duration_seconds"])
                    if r["duration_seconds"] is not None else None
                ),
                records_ingested=int(r["records_ingested"] or 0),
                error_message=r["error_message"],
            )
            for r in rows
        ],
        total=len(rows),
    )
