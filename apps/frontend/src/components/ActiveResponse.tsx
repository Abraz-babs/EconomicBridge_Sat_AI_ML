const events = [
  { name: 'Nigeria — Flood', sub: 'Borno State · Day 3', status: 'ACTIVE', cls: 's-active' },
  { name: 'Bangladesh — Cyclone', sub: "Cox's Bazar · 48h forecast", status: 'WATCH', cls: 's-watch' },
  { name: 'Mozambique — Drought', sub: 'Cabo Delgado · Week 6', status: 'MONITOR', cls: 's-monitor' },
  { name: 'Philippines — Landslide', sub: 'Mindanao · Recovery', status: 'RECOVERY', cls: 's-recovery' },
];

export default function ActiveResponse() {
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Active Response</span>
        <span className="panel-meta">7 events tracked</span>
      </div>
      <div>
        {events.map((e) => (
          <div key={e.name} className="event-row">
            <div>
              <div>{e.name}</div>
              <div className="event-sub">{e.sub}</div>
            </div>
            <span className={`status-tag ${e.cls}`}>{e.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
