'use client';

const barData = [
  { l: 'OCT', v: 68 },
  { l: 'NOV', v: 82 },
  { l: 'DEC', v: 75 },
  { l: 'JAN', v: 95 },
  { l: 'FEB', v: 88 },
  { l: 'MAR', v: 124 },
];

const maxV = Math.max(...barData.map((d) => d.v));

export default function CoverageTrend() {
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Coverage Trend</span>
        <span className="panel-meta">Mapped households / month</span>
      </div>
      <div className="bar-chart">
        <div style={{ fontSize: '9px', letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--muted)' }}>
          ×1,000 households
        </div>
        <div className="bars">
          {barData.map((d) => {
            const pct = (d.v / maxV) * 100;
            const col = d.l === 'MAR' ? '#2d6a4f' : '#52b788';
            return (
              <div key={d.l} className="bar-col">
                <div
                  className="bar-block"
                  style={{ height: `${pct}%`, background: col, opacity: 0.7 }}
                />
                <span className="bar-lbl">{d.l}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
