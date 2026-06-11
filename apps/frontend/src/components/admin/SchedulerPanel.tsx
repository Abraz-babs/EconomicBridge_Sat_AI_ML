'use client';

import { useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useRecentRuns,
  useRunSchedulerJob,
  useSchedulerJobs,
  useTriggerConflictPipeline,
} from '@/hooks/useScheduler';


/** "X min / h / d ago" against now. Null-safe. */
function fmtRel(isoOrNull: string | null): string {
  if (!isoOrNull) return '—';
  const ms = Date.now() - new Date(isoOrNull).getTime();
  if (ms < 0) {
    const futureMin = Math.round(-ms / 60_000);
    return futureMin < 60
      ? `in ${futureMin} min`
      : `in ${Math.round(futureMin / 60)} h`;
  }
  if (ms < 60_000) return 'just now';
  const min = Math.round(ms / 60_000);
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}


/** Hide the redundant "tzlocal()" suffix APScheduler prints on every trigger. */
function shortTrigger(t: string): string {
  return t
    .replace(/\s*[tT]ime[zZ]one='[^']+'/g, '')
    .replace(/\(\s*\)/g, '')
    .trim();
}


export default function SchedulerPanel() {
  const { activeTenantId, pilotTenants } = useTenant();
  const [conflictTenant, setConflictTenant] = useState(activeTenantId);
  const [lookbackDays, setLookbackDays] = useState(7);
  const [conflictResultText, setConflictResultText] = useState<string | null>(null);
  const [conflictError, setConflictError] = useState<string | null>(null);

  const jobsQuery = useSchedulerJobs();
  const runsQuery = useRecentRuns({ limit: 20 });
  const runJob = useRunSchedulerJob();
  const triggerConflict = useTriggerConflictPipeline();

  const [jobNote, setJobNote] = useState<string | null>(null);

  async function fireJob(jobId: string) {
    setJobNote(null);
    try {
      await runJob.mutateAsync({ jobId });
      // Jobs run in the background on the ingestion service (long sweeps
      // would otherwise 504 at the load balancer) — tell the operator where
      // to watch for the outcome.
      setJobNote(`${jobId} started — running in the background; refresh Recent Runs below.`);
      window.setTimeout(() => setJobNote(null), 10_000);
    } catch {
      /* surfaced via runJob.error below */
    }
  }

  async function fireConflict() {
    setConflictError(null);
    setConflictResultText(null);
    try {
      const r = await triggerConflict.mutateAsync({
        tenantId: conflictTenant, lookbackDays,
      });
      if (r.error) {
        setConflictError(r.error);
      } else {
        setConflictResultText(
          `${r.clusters_built} clusters · ${r.predictions_made} predictions · ` +
          `${r.alerts_written} alerts written` +
          (r.skipped_capped > 0 ? ` (${r.skipped_capped} capped)` : ''),
        );
      }
    } catch (err) {
      setConflictError(err instanceof Error ? err.message : 'Trigger failed');
    }
  }

  return (
    <div className="panel anim a2 sch-panel">
      <div className="panel-header">
        <span className="panel-title">Ingestion Scheduler — Live</span>
        <span className="panel-meta">
          {jobsQuery.data
            ? `${jobsQuery.data.jobs.length} jobs · ${jobsQuery.data.running ? 'running' : 'STOPPED'}`
            : jobsQuery.isLoading ? 'Loading…' : 'API unreachable'}
        </span>
      </div>

      {/* ─── Scheduled jobs + Run-Now ─── */}
      <div className="sch-section">
        <div className="sch-section-title">Scheduled jobs</div>
        {jobsQuery.isError && (
          <div className="fp-alert-error">
            Could not load scheduler jobs:{' '}
            {jobsQuery.error?.message ?? 'unknown'}. Is the ingestion
            service running on port 8001?
          </div>
        )}
        {jobsQuery.data && jobsQuery.data.jobs.length === 0 && (
          <div className="fp-alert-empty">No jobs registered.</div>
        )}
        {jobsQuery.data && jobsQuery.data.jobs.length > 0 && (
          <div className="sch-jobs">
            {jobsQuery.data.jobs.map((j) => {
              const pending =
                runJob.isPending && runJob.variables?.jobId === j.id;
              return (
                <div key={j.id} className="sch-job-row">
                  <div className="sch-job-name">
                    <div className="sch-job-title">{j.name}</div>
                    <div className="sch-job-meta">
                      <code>{j.id}</code> · {shortTrigger(j.trigger)}
                    </div>
                  </div>
                  <div className="sch-job-next">
                    Next: {fmtRel(j.next_run_time)}
                  </div>
                  <button
                    type="button"
                    className="cg-primary-btn sch-run-btn"
                    onClick={() => fireJob(j.id)}
                    disabled={pending}
                  >
                    {pending ? 'Running…' : 'Run now'}
                  </button>
                </div>
              );
            })}
          </div>
        )}
        {jobNote && <div className="sch-trigger-ok">✓ {jobNote}</div>}
        {runJob.error && (
          <div className="fp-alert-error">
            Job run failed: {runJob.error.message}
          </div>
        )}
      </div>

      {/* ─── Conflict trigger ─── */}
      <div className="sch-section">
        <div className="sch-section-title">Trigger conflict pipeline manually</div>
        <div className="sch-trigger-row">
          <label className="fp-tenant-label" htmlFor="sch-conflict-tenant">
            Tenant
          </label>
          <select
            id="sch-conflict-tenant"
            className="fp-tenant-select"
            value={conflictTenant}
            onChange={(e) => setConflictTenant(e.target.value)}
          >
            {pilotTenants.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>

          <label className="fp-tenant-label" htmlFor="sch-conflict-lookback">
            Lookback (days)
          </label>
          <input
            id="sch-conflict-lookback"
            className="sch-lookback-input"
            type="number"
            min={1}
            max={90}
            value={lookbackDays}
            onChange={(e) => setLookbackDays(Number(e.target.value) || 7)}
          />

          <button
            type="button"
            className="cg-primary-btn"
            onClick={fireConflict}
            disabled={triggerConflict.isPending}
          >
            {triggerConflict.isPending ? 'Running…' : 'Run sweep'}
          </button>
        </div>
        {conflictResultText && (
          <div className="sch-trigger-ok">✓ {conflictResultText}</div>
        )}
        {conflictError && (
          <div className="fp-alert-error">{conflictError}</div>
        )}
      </div>

      {/* ─── Recent runs ─── */}
      <div className="sch-section">
        <div className="sch-section-title">
          Recent runs
          <button
            type="button"
            className="sch-refresh-link"
            onClick={() => runsQuery.refetch()}
            disabled={runsQuery.isFetching}
          >
            {runsQuery.isFetching ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        {runsQuery.isError && (
          <div className="fp-alert-error">
            Could not load run history: {runsQuery.error?.message ?? 'unknown'}
          </div>
        )}
        {runsQuery.data && runsQuery.data.rows.length === 0 && (
          <div className="fp-alert-empty">
            No runs recorded yet. The scheduler writes to{' '}
            <code>public.ingestion_runs</code> on every fire.
          </div>
        )}
        {runsQuery.data && runsQuery.data.rows.length > 0 && (
          <div className="sch-runs-scroll">
            <table className="sch-runs">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Tenant</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Trigger</th>
                  <th>Records</th>
                  <th>Duration</th>
                </tr>
              </thead>
              <tbody>
                {runsQuery.data.rows.map((r) => (
                  <tr key={r.run_id}>
                    <td>{fmtRel(r.started_at)}</td>
                    <td>{r.tenant_id ?? '—'}</td>
                    <td>{r.source}</td>
                    <td>
                      <span
                        className={
                          r.status === 'succeeded'
                            ? 'sch-status sch-status--ok'
                            : r.status === 'failed'
                            ? 'sch-status sch-status--bad'
                            : 'sch-status'
                        }
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="sch-trigger-cell">{r.trigger}</td>
                    <td className="sch-num">{r.records_ingested}</td>
                    <td className="sch-num">
                      {r.duration_seconds != null
                        ? `${r.duration_seconds.toFixed(1)}s`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
