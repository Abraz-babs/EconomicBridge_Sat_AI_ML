'use client';

import { useMemo, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import { formatLatLon } from '@/lib/display';
import {
  useFarmlandAlerts,
  useFireStatus,
  useResolveAlert,
  type AlertResponse,
  type AlertSeverity,
} from '@/hooks/useFarmlandAlerts';
import FarmlandMap, { type FarmlandAlertPoint } from './FarmlandMap';

type MapLayerKey = 'heat' | 'ndvi' | 'sar' | 'boundary';

const mapLayers: { id: MapLayerKey; label: string }[] = [
  { id: 'heat', label: 'Heat' },
  { id: 'ndvi', label: 'NDVI' },
  { id: 'sar', label: 'SAR' },
  { id: 'boundary', label: 'Boundaries' },
];

// ─── Mapping helpers (server schema → display) ────────────────────────────

const SEV_DISPLAY: Record<AlertSeverity, { label: string; cls: string }> = {
  critical: { label: 'Critical', cls: 'fp-sev-crit' },
  high:     { label: 'High',     cls: 'fp-sev-high' },
  medium:   { label: 'Medium',   cls: 'fp-sev-med' },
  low:      { label: 'Low',      cls: 'fp-sev-med' },
};

const STATE_NAMES: Record<string, string> = {
  kebbi:    'Kebbi State',
  benue:    'Benue State',
  plateau:  'Plateau State',
  kaduna:   'Kaduna State',
  niger:    'Niger State',
  zamfara:  'Zamfara State',
  nasarawa: 'Nasarawa State',
  fct:      'Federal Capital Territory',
  ghana:    'Ghana',
  senegal:  'Senegal',
};

/** API alert → map pin shape (with the extras the hover tooltip reads). */
function toMapPoint(a: AlertResponse): FarmlandAlertPoint | null {
  if (!a.location) return null;
  return {
    id: a.id,
    location: `${STATE_NAMES[a.tenant_id] ?? a.tenant_id} — ${a.lga ?? a.zone_name ?? ''} LGA`,
    longitude: a.location.lon,
    latitude:  a.location.lat,
    // For map colour: resolved overrides severity (it goes green regardless).
    severity:  a.status === 'resolved' ? 'resolved' : a.severity,
    confidence: a.confidence_score ?? undefined,
    lga: a.lga,
    zoneName: a.zone_name,
    alertType: a.alert_type,
    status: a.status,
    affectedAreaHa: a.affected_area_ha,
    livelihoodsAtRisk: a.livelihoods_at_risk,
    predictedBreachHours: a.predicted_breach_hours,
    satelliteSource: a.satellite_source,
  };
}

/** Human-readable "X min ago" for the meta line. */
function relativeAge(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  const min = Math.round(ms / 60_000);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr} hr ago`;
  return `${Math.round(hr / 24)} d ago`;
}

function altLocation(a: AlertResponse): string {
  const marker = a.status === 'resolved' ? '✓' : '⚑';
  const state = STATE_NAMES[a.tenant_id] ?? a.tenant_id;
  const lga = a.lga ? `${a.lga} LGA` : (a.zone_name ?? '');
  return `${marker} ${state} — ${lga}`;
}

function altDescription(a: AlertResponse): string {
  if (a.zone_name && a.affected_area_ha != null && a.livelihoods_at_risk != null) {
    return (
      `${a.zone_name}. ~${a.affected_area_ha.toFixed(0)} ha at risk affecting ` +
      `${a.livelihoods_at_risk.toLocaleString()} livelihoods. ` +
      (a.satellite_source ? `Source: ${a.satellite_source}.` : '')
    );
  }
  return a.zone_name ?? 'Alert details pending review.';
}

function altMetaLine(a: AlertResponse): string[] {
  const parts: string[] = [];
  if (a.satellite_source) parts.push(`${a.satellite_source} · ${relativeAge(a.created_at)}`);
  if (a.confidence_score != null) parts.push(`Conf: ${Math.round(a.confidence_score * 100)}%`);
  if (a.predicted_breach_hours != null && a.status !== 'resolved') {
    parts.push(`ETA: ${a.predicted_breach_hours}h`);
  }
  if (a.status === 'resolved') parts.push('Resolved');
  else if (a.status === 'acknowledged') parts.push('Agency: Responding');
  return parts.length > 0 ? parts : [relativeAge(a.created_at)];
}

// ─── Live timeline derivation ─────────────────────────────────────────────

interface TimelineEvent {
  key: string;
  dot: 'fp-tl-crit' | 'fp-tl-warn' | 'fp-tl-ok';
  icon: string;
  time: string;
  event: string;
  detail: string;
  sortGroup: 0 | 1 | 2 | 3;
  sortKey: number;
}

function pastLabel(ageHours: number): string {
  if (ageHours < 1) return `${Math.round(ageHours * 60)}min ago`;
  if (ageHours < 48) return `${Math.round(ageHours)}h ago`;
  return `${Math.round(ageHours / 24)}d ago`;
}

/** Derive up to ~6 timeline rows from the active tenant's alerts. */
function deriveTimeline(alerts: AlertResponse[], stateLabel: string): TimelineEvent[] {
  const now = Date.now();
  const out: TimelineEvent[] = [];

  for (const a of alerts) {
    const lga = a.lga ?? a.zone_name ?? 'unspecified zone';
    const ageH = (now - new Date(a.created_at).getTime()) / 3_600_000;
    const conf = a.confidence_score != null
      ? `${Math.round(a.confidence_score * 100)}% confidence`
      : null;
    const agencies = a.agencies_notified?.length
      ? a.agencies_notified.join(' + ')
      : null;
    const ha = a.affected_area_ha;
    const liv = a.livelihoods_at_risk;

    // Group 0 — confirmed critical / high right now (top of timeline)
    if (
      a.status === 'pending_review' &&
      (a.severity === 'critical' || a.severity === 'high')
    ) {
      out.push({
        key: `${a.id}-now`,
        dot: a.severity === 'critical' ? 'fp-tl-crit' : 'fp-tl-warn',
        icon: '!',
        time: `Now — T+0h · ${stateLabel} ${lga}`,
        event:
          a.severity === 'critical'
            ? 'Encroachment confirmed — agency notification sent'
            : 'High-severity boundary alert raised',
        detail: [
          a.satellite_source,
          conf,
          agencies ? `${agencies} alerted` : null,
        ].filter(Boolean).join(' · '),
        sortGroup: 0,
        sortKey: ageH,  // most recent first
      });
    }

    // Group 1 — acknowledged (response in progress)
    if (a.status === 'acknowledged') {
      out.push({
        key: `${a.id}-ack`,
        dot: a.severity === 'critical' ? 'fp-tl-crit' : 'fp-tl-warn',
        icon: '~',
        time: `T+0h · ${lga} — Agency responding`,
        event: a.zone_name ?? `${lga} active response`,
        detail: [
          agencies ? `${agencies} engaged.` : null,
          ha != null ? `${Math.round(ha)} ha at risk` : null,
          liv != null ? `${liv.toLocaleString()} livelihoods.` : null,
        ].filter(Boolean).join(' '),
        sortGroup: 1,
        sortKey: ageH,
      });
    }

    // Group 2 — projected future breach (predicted by the model)
    if (a.status !== 'resolved' && a.predicted_breach_hours != null) {
      out.push({
        key: `${a.id}-proj`,
        dot: 'fp-tl-warn',
        icon: '~',
        time: `T+${a.predicted_breach_hours}h · Projected — ${lga}`,
        event: 'Predicted breach window',
        detail: [
          ha != null ? `~${Math.round(ha)} ha at risk` : null,
          liv != null ? `${liv.toLocaleString()} livelihoods` : null,
          a.satellite_source,
        ].filter(Boolean).join(' · '),
        sortGroup: 2,
        sortKey: a.predicted_breach_hours,  // soonest first
      });
    }

    // Group 3 — resolved (victories, bottom of timeline)
    if (a.status === 'resolved') {
      out.push({
        key: `${a.id}-res`,
        dot: 'fp-tl-ok',
        icon: '✓',
        time: `${pastLabel(ageH)} — Resolved · ${lga}`,
        event: a.zone_name ?? `${lga} alert resolved`,
        detail: [
          liv != null ? `~${liv.toLocaleString()} livelihoods protected.` : null,
          agencies ? `Engaged: ${agencies}.` : null,
        ].filter(Boolean).join(' ') || 'Resolved via mediation.',
        sortGroup: 3,
        sortKey: ageH,  // most recent resolution first
      });
    }
  }

  out.sort((a, b) =>
    a.sortGroup !== b.sortGroup ? a.sortGroup - b.sortGroup : a.sortKey - b.sortKey,
  );
  return out.slice(0, 6);
}

/** Format an NGN figure ≥ 0 into ₦X.XM / ₦XK / "—". */
function fmtNgn(value: number, isEcowas: boolean): string {
  if (isEcowas || value <= 0) return '—';
  if (value >= 1_000_000) return `₦${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `₦${Math.round(value / 1_000)}K`;
  return `₦${value.toLocaleString()}`;
}

/** Estimated economic value at risk per affected smallholder livelihood, in USD.
 *  Used for ECOWAS countries where the NGN value column isn't populated — a
 *  transparent first-order estimate (≈ a season's smallholder farm income). */
const USD_PER_LIVELIHOOD = 450;

/** Format a USD figure ≥ 0 into $X.XM / $XK / "—". */
function fmtUsd(value: number): string {
  if (value <= 0) return '—';
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${Math.round(value / 1_000)}K`;
  return `$${value.toLocaleString()}`;
}

function fmtScanAgo(iso: string | null): string {
  if (!iso) return 'awaiting first scan';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  const min = Math.round(ms / 60_000);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr} hr ago`;
  return `${Math.round(hr / 24)} d ago`;
}

// Fire activity in the pilot region peaks in the dry season (Nov–Mar);
// the wet months (Apr–Oct) are naturally near-zero. Used to label a 0-count
// honestly as "seasonally low" rather than implying the feed is dead.
function isLowFireSeason(): boolean {
  const m = new Date().getMonth(); // 0=Jan … 9=Oct
  return m >= 3 && m <= 9; // Apr–Oct
}

// Provenance buckets — derived from alert_events.model_name. Live rows
// come from real pipeline runs (conflict_predictor, ndvi_anomaly_detector,
// flood_detector, …); seed rows come from `scripts/seed_farmland_alerts.py`
// and tag themselves model_name='seed'. `null` is treated as seed too —
// older pre-pipeline rows that never got a model attribution.
type Provenance = 'all' | 'live' | 'seed';

function isSeedAlert(model_name: string | null): boolean {
  return model_name === null || model_name === 'seed';
}

function provenanceLabel(model_name: string | null): { text: string; cls: string } {
  return isSeedAlert(model_name)
    ? { text: 'SEED', cls: 'fp-prov fp-prov--seed' }
    : { text: 'LIVE', cls: 'fp-prov fp-prov--live' };
}

// ─── Component ────────────────────────────────────────────────────────────

export default function FarmlandPanel() {
  // Default to SAR — the radar backscatter is what the conflict / encroachment
  // model actually consumes. Heat is a secondary feeder signal (CLAUDE.md §2).
  const [activeMapLayer, setActiveMapLayer] = useState<MapLayerKey>('sar');
  // Default 'all' so the panel matches Slice 10's behaviour on first paint;
  // user opts into 'live' to see only pipeline-produced rows.
  const [provenance, setProvenance] = useState<Provenance>('all');
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();

  const query = useFarmlandAlerts({ tenantId: activeTenantId, perPage: 50 });
  const fireStatus = useFireStatus(activeTenantId);
  // Stabilise the alerts reference so downstream useMemo deps don't
  // re-fire every render (the `?? []` fallback would otherwise create
  // a fresh array each call).
  const allAlerts = useMemo(() => query.data?.alerts ?? [], [query.data]);
  // Filtered view used by the list + the map. Stats below intentionally
  // keep the unfiltered view so "Active Alerts: N" stays an honest tenant
  // total — the filter chips signal what the *user* is looking at, not
  // what the dashboard owns.
  const alerts = useMemo(() => {
    if (provenance === 'all') return allAlerts;
    if (provenance === 'live') return allAlerts.filter((a) => !isSeedAlert(a.model_name));
    return allAlerts.filter((a) => isSeedAlert(a.model_name));
  }, [allAlerts, provenance]);
  const liveCount = useMemo(
    () => allAlerts.filter((a) => !isSeedAlert(a.model_name)).length,
    [allAlerts],
  );
  const seedCount = allAlerts.length - liveCount;
  const resolveMutation = useResolveAlert(activeTenantId);

  // Map: only pins that have lat/lon. Map state changes when alerts change.
  const mapPoints = useMemo<FarmlandAlertPoint[]>(
    () => alerts.map(toMapPoint).filter((p): p is FarmlandAlertPoint => p !== null),
    [alerts],
  );

  // Stats derived from live data.
  const liveStats = useMemo(() => {
    const active = alerts.filter((a) => a.status !== 'resolved');
    const resolved = alerts.filter((a) => a.status === 'resolved');
    const farmsAtRiskHa = active.reduce((sum, a) => sum + (a.affected_area_ha ?? 0), 0);
    const livelihoodsProtected = resolved.reduce(
      (sum, a) => sum + (a.livelihoods_at_risk ?? 0),
      0,
    );
    const livelihoodsAtRisk = active.reduce(
      (sum, a) => sum + (a.livelihoods_at_risk ?? 0),
      0,
    );
    const economicValueAtRisk = active.reduce(
      (sum, a) => sum + (a.economic_value_ngn ?? 0),
      0,
    );
    const agencies = new Set<string>();
    alerts.forEach((a) => a.agencies_notified?.forEach((ag) => agencies.add(ag)));
    const satellites = new Set<string>();
    alerts.forEach((a) => a.satellite_source && satellites.add(a.satellite_source));
    const confidences = alerts
      .map((a) => a.confidence_score)
      .filter((c): c is number => c != null);
    const avgConfidence =
      confidences.length > 0
        ? confidences.reduce((s, c) => s + c, 0) / confidences.length
        : null;
    return {
      activeCount: active.length,
      farmsAtRiskHa,
      resolvedCount: resolved.length,
      livelihoodsAtRisk,
      livelihoodsProtected,
      economicValueAtRisk,
      avgConfidence,
      agenciesCount: agencies.size,
      agencies: Array.from(agencies),
      satellites: Array.from(satellites),
      activeBreakdown: active.reduce<Record<string, number>>(
        (acc, a) => ({ ...acc, [a.severity]: (acc[a.severity] ?? 0) + 1 }),
        {},
      ),
    };
  }, [alerts]);

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const isEcowas = activeTenant.type === 'ecowas_country';

  // Derive the timeline rows from the live alerts.
  const timelineEvents = useMemo(
    () => deriveTimeline(alerts, stateLabel),
    [alerts, stateLabel],
  );

  return (
    <div>
      {/* HEADER */}
      <div className="fp-header">
        <div>
          <div className="fp-title">Farmland Protection &amp; Livelihood Alert System</div>
          <div className="fp-subtitle">Encroachment prediction · Copernicus Sentinel-1 SAR · 48–72hr conflict-risk window · Heat &amp; NDVI as supporting signals</div>
        </div>
        <div
          className={`fp-live-badge ${
            !query.isLoading && !query.isError && liveCount === 0
              ? 'fp-live-badge--monitoring'
              : ''
          }`}
        >
          <div className="fp-pulse" />
          {query.isLoading
            ? 'LOADING'
            : query.isError
            ? 'API UNREACHABLE'
            : (
                <>
                  {/* "LIVE" only when the pipeline has produced live alerts;
                     otherwise "MONITORING" (watch on, none active) — so the
                     status word never contradicts the "N live" count beside
                     it, and an all-clear state doesn't show alert-red. */}
                  {liveCount > 0 ? 'LIVE' : 'MONITORING'} — {stateLabel} ·{' '}
                  {allAlerts.length} alerts ·{' '}
                  <span className="fp-live-split">
                    {liveCount} live, {seedCount} seed
                  </span>
                </>
              )}
        </div>
      </div>

      {/* TENANT SELECTOR */}
      <div className="fp-tenant-bar">
        <label htmlFor="fp-tenant-select" className="fp-tenant-label">
          Viewing tenant
        </label>
        <select
          id="fp-tenant-select"
          className="fp-tenant-select"
          value={activeTenantId}
          onChange={(e) => setActiveTenant(e.target.value)}
        >
          {pilotTenants.map((t) => (
            <option key={t.id} value={t.id}>
              {STATE_NAMES[t.id] ?? t.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="fp-refresh-btn"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          {query.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>

        {/* Provenance filter — show all rows, only live pipeline rows, or
           only seed/baseline rows. Client-side: model_name is already on
           each row, so no extra fetch needed. */}
        <div
          className="fp-prov-chips"
          role="group"
          aria-label="Filter alerts by data source"
        >
          {(['all', 'live', 'seed'] as Provenance[]).map((p) => (
            <button
              key={p}
              type="button"
              className={`fp-prov-chip ${provenance === p ? 'is-active' : ''}`}
              onClick={() => setProvenance(p)}
              title={
                p === 'live'
                  ? 'Pipeline-produced alerts (FIRMS → conflict_predictor, NDVI anomaly, flood detector, …)'
                  : p === 'seed'
                  ? 'Baseline rows seeded by scripts/seed_farmland_alerts.py'
                  : 'Show all alerts regardless of source'
              }
            >
              {p === 'all' ? 'All' : p === 'live' ? `Live (${liveCount})` : `Seed (${seedCount})`}
            </button>
          ))}
        </div>
      </div>

      {/* NASA FIRMS fire-feed status — proves the daily fire ingest is live
          even out of fire season (detections are seasonally near-zero in the
          wet months). Amber when fires are currently detected. */}
      {fireStatus.data && (() => {
        const fs = fireStatus.data;
        const active = fs.detections24h > 0;
        return (
          <div
            style={{
              display: 'flex', alignItems: 'center', gap: '8px',
              margin: '0 0 12px', padding: '7px 12px', borderRadius: '6px',
              fontSize: '12.5px',
              background: active ? 'rgba(234,179,8,0.10)' : 'rgba(34,197,94,0.10)',
              border: `1px solid ${active ? 'rgba(234,179,8,0.35)' : 'rgba(34,197,94,0.30)'}`,
              color: 'var(--text-secondary, #94a3b8)',
            }}
          >
            <span
              aria-hidden
              style={{
                width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
                background: active ? '#eab308' : '#22c55e',
                boxShadow: `0 0 6px ${active ? '#eab308' : '#22c55e'}`,
              }}
            />
            <span>
              Fire detections (NASA FIRMS):{' '}
              <strong>{fs.detections24h} today</strong>
              {fs.detections7d > 0 ? ` · ${fs.detections7d} in 7d` : ''}
              {!active && isLowFireSeason() ? ' · seasonally low' : ''}
              {' · last scan '}{fmtScanAgo(fs.lastScanAt)}
            </span>
          </div>
        );
      })()}

      {/* STATS (live) */}
      <div className="fp-grid">
        <div className="fp-stat crit">
          <div className="fp-stat-label">Active Alerts</div>
          <div className="fp-stat-val">{liveStats.activeCount}</div>
          <div className="fp-stat-sub">
            {liveStats.activeBreakdown.critical ?? 0} critical ·{' '}
            {liveStats.activeBreakdown.high ?? 0} high
          </div>
        </div>
        <div className="fp-stat warn">
          <div className="fp-stat-label">Farms Under Threat (ha)</div>
          <div className="fp-stat-val">
            {liveStats.farmsAtRiskHa.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </div>
          <div className="fp-stat-sub">Across active alerts in {stateLabel}</div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">Resolved (window)</div>
          <div className="fp-stat-val">{liveStats.resolvedCount}</div>
          <div className="fp-stat-sub">
            ~{liveStats.livelihoodsProtected.toLocaleString()} livelihoods protected
          </div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">Agencies Notified</div>
          <div className="fp-stat-val">{liveStats.agenciesCount}</div>
          <div className="fp-stat-sub">Unique recipients across all alerts</div>
        </div>
      </div>

      {/* MAP + ALERT FEED */}
      <div className="fp-main-row">
        <div className="fp-map">
          <div className="fp-map-header">
            <span className="fp-map-title">
              Encroachment &amp; Boundary Monitor — {stateLabel}
            </span>
            <div className="fp-map-controls">
              {mapLayers.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  className={`fp-layer-btn ${activeMapLayer === l.id ? 'active' : ''}`}
                  onClick={() => setActiveMapLayer(l.id)}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          <FarmlandMap
            alerts={mapPoints}
            activeLayer={activeMapLayer}
            tenant={activeTenant}
          />
        </div>

        <div className="fp-alerts">
          <div className="fp-alerts-header">
            Active Encroachment Alerts
            <span className="fp-alert-count">{liveStats.activeCount} ACTIVE</span>
          </div>
          {query.isLoading && (
            <div className="fp-alert-empty">Loading alerts…</div>
          )}
          {query.isError && (
            <div className="fp-alert-error">
              Could not load alerts: {query.error?.message ?? 'unknown error'}
              {query.error?.code === 'TENANT_NOT_FOUND' && (
                <> — tenant <code>{activeTenantId}</code> is not provisioned yet.</>
              )}
            </div>
          )}
          {!query.isLoading && !query.isError && alerts.length === 0 && (
            <div className="fp-alert-empty">
              No alerts for {stateLabel}. Run{' '}
              <code>python -m scripts.seed_farmland_alerts</code> from{' '}
              <code>apps/api/</code> to populate sample data.
            </div>
          )}
          {alerts.length === 0 && !query.isLoading && !query.isError && allAlerts.length > 0 && (
            <div className="fp-alert-empty">
              No {provenance} alerts in {stateLabel} right now.
              {provenance === 'live' && allAlerts.length > 0 && (
                <>
                  {' '}Try clicking <strong>All</strong> above to see seed/baseline rows,
                  or run a fresh pipeline sweep:{' '}
                  <code>POST /api/v1/ingest/conflict</code> with{' '}
                  <code>tenant_id=&quot;{activeTenantId}&quot;</code>.
                </>
              )}
            </div>
          )}
          {alerts.map((a) => {
            const sev = SEV_DISPLAY[a.severity];
            const showResolved = a.status === 'resolved';
            const pendingResolve =
              resolveMutation.isPending && resolveMutation.variables?.alertId === a.id;
            const prov = provenanceLabel(a.model_name);
            return (
              <div key={a.id} className="fp-alert-item">
                <div className="fp-alert-top">
                  <span className="fp-alert-location">{altLocation(a)}</span>
                  <span
                    className={prov.cls}
                    title={a.model_name ? `Source: ${a.model_name}` : 'Seed / baseline row'}
                  >
                    {prov.text}
                  </span>
                  <span
                    className={`fp-sev ${showResolved ? 'fp-sev-med' : sev.cls}`}
                  >
                    {showResolved ? 'Resolved' : sev.label}
                  </span>
                </div>
                <div className="fp-alert-desc">{altDescription(a)}</div>
                <div className="fp-alert-meta">
                  {altMetaLine(a).map((m, i) => (
                    <span key={i}>{m}</span>
                  ))}
                </div>
                {a.location && (
                  <div className="fp-alert-coords">
                    📍 {formatLatLon(a.location.lat, a.location.lon)}
                    {a.lga ? ` · ${a.lga} LGA` : ''}
                  </div>
                )}
                {!showResolved && (
                  <div className="fp-alert-actions">
                    <button
                      type="button"
                      className={`fp-resolve-btn ${pendingResolve ? 'is-pending' : ''}`}
                      disabled={resolveMutation.isPending}
                      onClick={() =>
                        resolveMutation.mutate({ alertId: a.id, status: 'resolved' })
                      }
                    >
                      {pendingResolve ? 'Marking…' : 'Mark resolved'}
                    </button>
                    {a.status !== 'acknowledged' && (
                      <button
                        type="button"
                        className="fp-resolve-btn"
                        disabled={resolveMutation.isPending}
                        onClick={() =>
                          resolveMutation.mutate({
                            alertId: a.id,
                            status: 'acknowledged',
                          })
                        }
                      >
                        Acknowledge
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* PREDICTION TIMELINE + ECONOMIC IMPACT — both panels are LIVE */}
      <div className="fp-main-row fp-main-row--equal">
        <div className="fp-timeline">
          <div className="fp-timeline-header">
            48–72 Hour Conflict Prediction Timeline — {stateLabel}
          </div>
          <div className="fp-timeline-body">
            {timelineEvents.length === 0 ? (
              <div className="fp-alert-empty">
                No active or recently-resolved events in {stateLabel}. The
                timeline populates as alerts arrive from the ingestion pipeline.
              </div>
            ) : (
              timelineEvents.map((e) => (
                <div key={e.key} className="fp-tl-row">
                  <div className={`fp-tl-dot ${e.dot}`}>{e.icon}</div>
                  <div className="fp-tl-content">
                    <div className="fp-tl-time">{e.time}</div>
                    <div className="fp-tl-event">{e.event}</div>
                    <div className="fp-tl-detail">{e.detail}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="fp-timeline">
          <div className="fp-timeline-header">
            Economic Livelihood Protection — {stateLabel}
          </div>
          <div className="fp-timeline-body fp-impact-body">
            <div className="fp-impact-row fp-impact-row--bordered">
              <div>
                <div className="fp-impact-label">Conflicts Prevented</div>
                <div className="fp-impact-val">{liveStats.resolvedCount}</div>
                <div className="fp-impact-desc">
                  Verified resolutions via mediation or rerouting
                </div>
              </div>
              <div>
                <div className="fp-impact-label">Livelihoods Protected</div>
                <div className="fp-impact-val">
                  ~{liveStats.livelihoodsProtected.toLocaleString()}
                </div>
                <div className="fp-impact-desc">
                  {liveStats.livelihoodsAtRisk > 0
                    ? `${liveStats.livelihoodsAtRisk.toLocaleString()} still at risk in ${liveStats.activeCount} active alert${liveStats.activeCount === 1 ? '' : 's'}`
                    : 'Sum of livelihoods on resolved alerts'}
                </div>
              </div>
              <div>
                <div className="fp-impact-label">Economic Value at Risk</div>
                <div className="fp-impact-val fp-impact-val--small">
                  {isEcowas
                    ? fmtUsd(liveStats.livelihoodsAtRisk * USD_PER_LIVELIHOOD)
                    : fmtNgn(liveStats.economicValueAtRisk, isEcowas)}
                </div>
                <div className="fp-impact-desc">
                  {isEcowas
                    ? `Est. ~$${USD_PER_LIVELIHOOD}/livelihood across ${liveStats.livelihoodsAtRisk.toLocaleString()} at risk`
                    : `Aggregated across ${liveStats.activeCount} active alert${liveStats.activeCount === 1 ? '' : 's'}`}
                </div>
              </div>
            </div>

            <div className="fp-impact-footnote">
              {liveStats.satellites.length > 0 ? (
                <>
                  Data sources for {stateLabel}:{' '}
                  {liveStats.satellites.map((s, i) => (
                    <span key={s}>
                      <code>{s}</code>
                      {i < liveStats.satellites.length - 1 ? ', ' : ''}
                    </span>
                  ))}
                  . AI model: Random Forest conflict predictor (Citadel-proven)
                  {liveStats.avgConfidence != null
                    ? ` · ${Math.round(liveStats.avgConfidence * 100)}% mean confidence`
                    : ''}
                  . {alerts.length} alert{alerts.length === 1 ? '' : 's'} in window
                  {liveStats.agenciesCount > 0
                    ? `, ${liveStats.agenciesCount} agenc${liveStats.agenciesCount === 1 ? 'y' : 'ies'} engaged`
                    : ''}
                  .
                </>
              ) : (
                <>
                  No active feeds for {stateLabel}. Ingestion will populate this
                  panel once the satellite pipeline runs for tenant{' '}
                  <code>{activeTenantId}</code>.
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
