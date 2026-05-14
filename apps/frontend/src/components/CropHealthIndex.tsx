const crops = [
  { name: 'Maize — Kenya', pct: 78, color: '#52b788' },
  { name: 'Rice — Myanmar', pct: 62, color: '#f4a832' },
  { name: 'Cassava — Malawi', pct: 31, color: '#e05a2b' },
  { name: 'Wheat — Ethiopia', pct: 85, color: '#52b788' },
  { name: 'Sorghum — Niger', pct: 44, color: '#f4a832' },
];

export default function CropHealthIndex() {
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Crop Health Index</span>
        <span className="panel-meta">AI + NDVI analysis</span>
      </div>
      <div>
        {crops.map((c) => (
          <div key={c.name} className="crop-row">
            <span>{c.name}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div className="progress-wrap">
                <div className="progress-bar" style={{ width: `${c.pct}%`, background: c.color }} />
              </div>
              <span style={{ fontSize: '9px', color: 'var(--muted)', width: '26px', textAlign: 'right' }}>
                {c.pct}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
