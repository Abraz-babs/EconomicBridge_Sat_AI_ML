'use client';

import { useMemo, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useFarmlandAlerts,
  type AlertResponse,
  type AlertSeverity,
} from '@/hooks/useFarmlandAlerts';
import FarmlandMap, { type FarmlandAlertPoint } from './FarmlandMap';

// ─── Static fixtures retained for the timeline + economic-impact panels ───
// (These are aggregated narrative views; they'll be replaced by their own
// endpoints in later steps. The map + alert feed below are now LIVE.)

const timelineEvents = [
  { dot: 'fp-tl-crit', icon: '!', time: 'Now — T+0h · Kebbi Argungu', event: 'Encroachment confirmed — agency notification sent', detail: 'Copernicus SAR + heat overlay · 94% confidence · NEMA + Min. Agriculture alerted' },
  { dot: 'fp-tl-warn', icon: '~', time: 'T+6h · Projected', event: 'Herder group reaches active maize field boundary', detail: 'If unresolved — estimated 80+ ha at risk. Mediation window closing.' },
  { dot: 'fp-tl-warn', icon: '~', time: 'T+24h · Plateau Shendam', event: 'Western boundary breach probability: 71%', detail: 'Pre-emptive alert issued. State mediators en route. Sentinel-2 optical pass scheduled.' },
  { dot: 'fp-tl-warn', icon: '~', time: 'T+48h · Kaduna Kachia', event: 'Sorghum belt migration overlap — seasonal peak risk', detail: 'Historical conflict zone. Extension officer engaged. Designated grazing corridor opened.' },
  { dot: 'fp-tl-ok', icon: '✓', time: 'Yesterday — Resolved', event: 'Birnin Kebbi alert resolved via mediation', detail: 'Herders rerouted. No crop damage. $48,000 livelihood protected. Response time: 3.5 hrs.' },
];

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
  fct:      'Federal Capital Territory',
  ghana:    'Ghana',
  senegal:  'Senegal',
};

/** API alert → map pin shape. */
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

// ─── Component ────────────────────────────────────────────────────────────

export default function FarmlandPanel() {
  const [activeMapLayer, setActiveMapLayer] = useState<MapLayerKey>('heat');
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();

  const query = useFarmlandAlerts({ tenantId: activeTenantId, perPage: 50 });
  const alerts = query.data?.alerts ?? [];

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
    const agencies = new Set<string>();
    alerts.forEach((a) => a.agencies_notified?.forEach((ag) => agencies.add(ag)));
    return {
      activeCount: active.length,
      farmsAtRiskHa,
      resolvedCount: resolved.length,
      livelihoodsProtected,
      agenciesCount: agencies.size,
      activeBreakdown: active.reduce<Record<string, number>>(
        (acc, a) => ({ ...acc, [a.severity]: (acc[a.severity] ?? 0) + 1 }),
        {},
      ),
    };
  }, [alerts]);

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;

  return (
    <div>
      {/* HEADER */}
      <div className="fp-header">
        <div>
          <div className="fp-title">Farmland Protection &amp; Livelihood Alert System</div>
          <div className="fp-subtitle">Copernicus SAR · Heat Signature Analysis · 48–72hr Conflict Prediction Window</div>
        </div>
        <div className="fp-live-badge">
          <div className="fp-pulse" />
          {query.isLoading
            ? 'LOADING'
            : query.isError
            ? 'API UNREACHABLE'
            : `LIVE — ${stateLabel} · ${alerts.length} alerts`}
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
      </div>

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
              Satellite Heat &amp; Boundary Overlay — {stateLabel}
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
          <FarmlandMap alerts={mapPoints} activeLayer={activeMapLayer} />
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
          {alerts.map((a) => {
            const sev = SEV_DISPLAY[a.severity];
            const showResolved = a.status === 'resolved';
            return (
              <div key={a.id} className="fp-alert-item">
                <div className="fp-alert-top">
                  <span className="fp-alert-location">{altLocation(a)}</span>
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
              </div>
            );
          })}
        </div>
      </div>

      {/* PREDICTION TIMELINE + ECONOMIC IMPACT — narrative panels, static for now */}
      <div className="fp-main-row fp-main-row--equal">
        <div className="fp-timeline">
          <div className="fp-timeline-header">48–72 Hour Conflict Prediction Timeline</div>
          <div className="fp-timeline-body">
            {timelineEvents.map((e, i) => (
              <div key={i} className="fp-tl-row">
                <div className={`fp-tl-dot ${e.dot}`}>{e.icon}</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">{e.time}</div>
                  <div className="fp-tl-event">{e.event}</div>
                  <div className="fp-tl-detail">{e.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="fp-timeline">
          <div className="fp-timeline-header">Economic Livelihood Protection — 30-Day Summary</div>
          <div className="fp-timeline-body fp-impact-body">
            <div className="fp-impact-row fp-impact-row--bordered">
              <div>
                <div className="fp-impact-label">Conflicts Prevented</div>
                <div className="fp-impact-val">{liveStats.resolvedCount}</div>
                <div className="fp-impact-desc">Verified resolutions via mediation or rerouting</div>
              </div>
              <div>
                <div className="fp-impact-label">Livelihoods Protected</div>
                <div className="fp-impact-val">
                  ~{liveStats.livelihoodsProtected.toLocaleString()}
                </div>
                <div className="fp-impact-desc">Sum of livelihoods_at_risk on resolved alerts</div>
              </div>
              <div>
                <div className="fp-impact-label">Agencies Engaged</div>
                <div className="fp-impact-val fp-impact-val--small">{liveStats.agenciesCount}</div>
                <div className="fp-impact-desc">Distinct agencies across all alerts</div>
              </div>
            </div>

            <div className="fp-impact-footnote">
              Data sources: Copernicus Sentinel-1 SAR (all-weather), Sentinel-2 optical, NASA FIRMS heat, N2YO live pass tracking. AI model: Random Forest conflict predictor + DBSCAN spatial clustering. Live data from <code>{activeTenantId}</code>.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
