'use client';

import { useProvenance, type FeedProvenance } from '@/hooks/useProvenance';

const KIND_STYLE: Record<FeedProvenance['kind'], { label: string; color: string }> = {
  live: { label: 'LIVE SATELLITE', color: '#16a34a' },
  modelled: { label: 'MODELLED', color: '#eab308' },
  derived: { label: 'DERIVED', color: '#3b82f6' },
};

const card: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border2)',
  borderRadius: '8px',
  padding: '12px 14px',
};

function FeedCard({ f }: { f: FeedProvenance }) {
  const k = KIND_STYLE[f.kind];
  return (
    <div style={{ ...card, borderLeft: `4px solid ${k.color}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '4px' }}>
        <strong style={{ fontSize: '14px' }}>{f.module}</strong>
        <span style={{
          background: k.color, color: '#0c0f0a', fontWeight: 700, fontSize: '10px',
          letterSpacing: '0.04em', padding: '2px 7px', borderRadius: '10px',
        }}>{k.label}</span>
      </div>
      <div style={{ fontSize: '12.5px', marginBottom: '6px', opacity: 0.9 }}>{f.signal}</div>
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
        {f.satellites.map((s) => (
          <span key={s} style={{
            fontSize: '11px', fontFamily: "'DM Mono', monospace",
            background: 'rgba(0,0,0,0.05)', border: '1px solid var(--border2)',
            borderRadius: '4px', padding: '2px 7px',
          }}>🛰 {s}</span>
        ))}
      </div>
      <div style={{ fontSize: '11.5px', lineHeight: 1.5 }}>
        <div><strong>Licence:</strong> {f.license}</div>
        <div><strong>Refresh:</strong> {f.cadence}</div>
        <div style={{ opacity: 0.75, marginTop: '4px' }}>{f.attribution}</div>
      </div>
    </div>
  );
}

export default function ProvenancePanel() {
  const { data, isLoading, isError } = useProvenance();

  return (
    <section className="sb-table-wrap" style={{ marginTop: '16px' }} aria-label="Data sources and provenance">
      <div className="cg-section-header">Data Sources &amp; Provenance — where every layer comes from</div>
      {isLoading && <div className="fp-alert-empty">Loading provenance…</div>}
      {isError && <div className="fp-alert-empty">Couldn&apos;t load provenance.</div>}
      {data && (
        <>
          <div className="ev-map-meta" style={{ margin: '4px 0 12px', lineHeight: 1.5 }}>
            ✅ {data.summary}
          </div>
          <div style={{
            display: 'grid', gap: '10px',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
          }}>
            {data.feeds.map((f) => <FeedCard key={f.module} f={f} />)}
          </div>
          <div style={{ ...card, marginTop: '12px', borderLeft: '4px solid #6366f1' }}>
            <strong style={{ fontSize: '13px' }}>Satellite compute — {data.compute.provider}</strong>
            <div style={{ fontSize: '12px', marginTop: '4px' }}>
              {data.compute.tier} tier · {data.compute.monthly_pu.toLocaleString()} Processing
              Units + {data.compute.monthly_requests.toLocaleString()} requests / month
            </div>
            <div className="ev-map-meta" style={{ marginTop: '6px', lineHeight: 1.5 }}>{data.compute.note}</div>
          </div>
        </>
      )}
    </section>
  );
}
