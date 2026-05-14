'use client';

import { useState } from 'react';
import FarmlandMap, { type FarmlandAlertPoint } from './FarmlandMap';

const stats = [
  { label: 'Active Encroachment Alerts', val: '7', sub: '↑ 3 since yesterday · Kebbi, Zamfara, Plateau', cls: 'crit' },
  { label: 'Farms Under Threat (ha)', val: '14,200', sub: 'Across 4 LGAs · 72hr prediction window', cls: 'warn' },
  { label: 'Conflicts Prevented (30d)', val: '23', sub: '↑ 8 from last month · $1.15M livelihood protected', cls: 'ok' },
  { label: 'Agencies Notified', val: '11', sub: 'Min. Agric. · NEMA · 9 State agencies', cls: 'ok' },
];

interface PanelAlert extends FarmlandAlertPoint {
  sev: string;
  sevCls: string;
  desc: string;
  meta: string[];
}

const alerts: PanelAlert[] = [
  {
    id: 'argungu',
    location: '⚑ Kebbi — Argungu LGA',
    longitude: 4.5253, latitude: 12.7444,
    severity: 'critical', confidence: 0.94,
    sev: 'Critical', sevCls: 'fp-sev-crit',
    desc: 'Large herder group detected 2.3km inside protected farmland boundary. Heat signature consistent with 400+ cattle. Trajectory toward active maize fields.',
    meta: ['SAR · 14 min ago', 'Conf: 94%', 'ETA conflict: 6–8 hrs'],
  },
  {
    id: 'anka',
    location: '⚑ Zamfara — Anka LGA',
    longitude: 5.9333, latitude: 12.1056,
    severity: 'critical', confidence: 0.91,
    sev: 'Critical', sevCls: 'fp-sev-crit',
    desc: 'Boundary breach confirmed. Heat cluster (est. 250 cattle) at 1.1km depth. Min. of Agriculture notified. Response team dispatched.',
    meta: ['SAR + NDVI · 38 min ago', 'Conf: 91%', 'Agency: Responding'],
  },
  {
    id: 'shendam',
    location: '⚑ Plateau — Shendam LGA',
    longitude: 9.5380, latitude: 8.8833,
    severity: 'high', confidence: 0.87,
    sev: 'High', sevCls: 'fp-sev-high',
    desc: 'Herder movement approaching western farmland boundary. 48hr window. No breach yet — pre-emptive alert issued to state mediators.',
    meta: ['SAR · 1 hr ago', 'Conf: 87%', 'Window: 48 hrs'],
  },
  {
    id: 'kachia',
    location: '⚑ Kaduna — Kachia LGA',
    longitude: 7.9490, latitude: 9.8676,
    severity: 'high', confidence: 0.82,
    sev: 'High', sevCls: 'fp-sev-high',
    desc: 'Seasonal migration route overlapping sorghum belt. Historical conflict zone — elevated risk. Extension officer alerted.',
    meta: ['SAR · 2 hrs ago', 'Conf: 82%', 'Window: 72 hrs'],
  },
  {
    id: 'birnin_kebbi',
    location: '✓ Kebbi — Birnin Kebbi LGA',
    longitude: 4.1994, latitude: 12.4539,
    severity: 'resolved',
    sev: 'Resolved', sevCls: 'fp-sev-med',
    desc: 'Yesterday\'s alert resolved. NEMA mediation successful. Herders rerouted via designated corridor. No crop damage recorded.',
    meta: ['Resolved 4 hrs ago', 'Livelihood saved: ~$48K'],
  },
];

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

export default function FarmlandPanel() {
  const [activeMapLayer, setActiveMapLayer] = useState<MapLayerKey>('heat');

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
          LIVE — SAR Pass 14 min ago
        </div>
      </div>

      {/* STATS */}
      <div className="fp-grid">
        {stats.map((s) => (
          <div key={s.label} className={`fp-stat ${s.cls}`}>
            <div className="fp-stat-label">{s.label}</div>
            <div className="fp-stat-val">{s.val}</div>
            <div className="fp-stat-sub">{s.sub}</div>
          </div>
        ))}
      </div>

      {/* MAP + ALERT FEED */}
      <div className="fp-main-row">
        {/* SAR MAP */}
        <div className="fp-map">
          <div className="fp-map-header">
            <span className="fp-map-title">Satellite Heat &amp; Boundary Overlay — Northwest Nigeria</span>
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
          <FarmlandMap alerts={alerts} activeLayer={activeMapLayer} />
        </div>

        {/* ALERT FEED */}
        <div className="fp-alerts">
          <div className="fp-alerts-header">
            Active Encroachment Alerts
            <span className="fp-alert-count">7 ACTIVE</span>
          </div>
          {alerts.map((a, i) => (
            <div key={i} className="fp-alert-item">
              <div className="fp-alert-top">
                <span className="fp-alert-location">{a.location}</span>
                <span className={`fp-sev ${a.sevCls}`}>{a.sev}</span>
              </div>
              <div className="fp-alert-desc">{a.desc}</div>
              <div className="fp-alert-meta">
                {a.meta.map((m, j) => (
                  <span key={j}>{m}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* PREDICTION TIMELINE + ECONOMIC IMPACT */}
      <div className="fp-main-row" style={{ gridTemplateColumns: '1fr 1fr' }}>
        {/* PREDICTION TIMELINE */}
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

        {/* ECONOMIC IMPACT */}
        <div className="fp-timeline">
          <div className="fp-timeline-header">Economic Livelihood Protection — 30-Day Summary</div>
          <div className="fp-timeline-body" style={{ padding: 0 }}>
            <div className="fp-impact-row" style={{ padding: '16px', borderBottom: '1px solid var(--border)' }}>
              <div>
                <div className="fp-impact-label">Conflicts Prevented</div>
                <div className="fp-impact-val">23</div>
                <div className="fp-impact-desc">Verified resolutions via mediation or rerouting</div>
              </div>
              <div>
                <div className="fp-impact-label">Livelihoods Protected</div>
                <div className="fp-impact-val">$1.15M</div>
                <div className="fp-impact-desc">Crop loss + displacement cost averted</div>
              </div>
              <div>
                <div className="fp-impact-label">Avg. Response Time</div>
                <div className="fp-impact-val" style={{ fontSize: '18px' }}>4.2 hrs</div>
                <div className="fp-impact-desc">From SAR detection to agency on ground</div>
              </div>
            </div>

            <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: '9px', letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '10px' }}>
                Economic Value Per Intervention
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
                {[
                  { label: 'Crop loss prevented (avg/incident)', val: '$28,400' },
                  { label: 'Displacement cost averted (avg)', val: '$21,600' },
                  { label: 'Emergency relief cost averted', val: '$9,800' },
                ].map((r) => (
                  <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '10px' }}>
                    <span style={{ color: 'var(--ink2)' }}>{r.label}</span>
                    <span style={{ color: 'var(--ok)', fontWeight: 500 }}>{r.val}</span>
                  </div>
                ))}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '10px', paddingTop: '7px', borderTop: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--ink)', fontWeight: 500 }}>Total value per prevented conflict</span>
                  <span style={{ color: 'var(--ok)', fontWeight: 700, fontSize: '12px' }}>~$59,800</span>
                </div>
              </div>
            </div>

            <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: '9px', letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '10px' }}>
                Agencies Receiving Alerts
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {[
                  { label: 'MIN. AGRICULTURE', bg: 'var(--gov-light)', color: 'var(--gov)' },
                  { label: 'NEMA', bg: 'var(--gov-light)', color: 'var(--gov)' },
                  { label: 'STATE AGRIC. DEPT.', bg: 'var(--gov-light)', color: 'var(--gov)' },
                  { label: 'CARE INTL', bg: 'var(--ngo-light)', color: 'var(--ngo)' },
                  { label: 'FAO NIGERIA', bg: 'var(--ngo-light)', color: 'var(--ngo)' },
                  { label: 'WFP', bg: 'var(--intl-light)', color: 'var(--intl)' },
                  { label: 'EXT. OFFICERS', bg: 'var(--research-light)', color: 'var(--research)' },
                ].map((a) => (
                  <span
                    key={a.label}
                    style={{ padding: '3px 9px', background: a.bg, color: a.color, fontSize: '9px', borderRadius: '2px', letterSpacing: '1px' }}
                  >
                    {a.label}
                  </span>
                ))}
              </div>
            </div>

            <div style={{ padding: '12px 16px', fontSize: '10px', color: 'var(--muted)', lineHeight: 1.6 }}>
              Data sources: Copernicus Sentinel-1 SAR (all-weather), Sentinel-2 optical, NASA FIRMS heat, N2YO live pass tracking. AI model: Random Forest conflict predictor + DBSCAN spatial clustering. Prediction accuracy: 89% (30-day rolling).
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
