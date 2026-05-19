"""GET /api/v1/scheduler/jobs — introspect the in-process scheduler.

Read-only listing of jobs registered with the APScheduler instance
attached to `app.state` during lifespan startup. Useful both as a
health check (is the scheduler running?) and as a quick sanity check
for the cron expressions during deployment.

Also exposes POST /api/v1/scheduler/jobs/{job_id}/run — manually fire
a registered job's body. Useful for testing the cron-driven flow
without waiting for 06:00 UTC.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from scheduler import JOB_ID_FIRMS_DAILY, run_daily_firms_ingest

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
}


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
