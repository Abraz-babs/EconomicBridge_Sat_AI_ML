const feedItems = [
  { color: '#e05a2b', text: 'Flood extent +18% — Borno State, Nigeria', tag: 'Disaster', tagClass: 'tag-d', time: '14 min ago' },
  { color: '#f4a832', text: 'Uncharted settlement detected — Kivu Province, DRC', tag: 'Poverty', tagClass: 'tag-p', time: '1h ago' },
  { color: '#52b788', text: 'Cassava mosaic disease — 340 ha at risk, Malawi', tag: 'Agriculture', tagClass: 'tag-a', time: '2h ago' },
  { color: '#e05a2b', text: 'Cyclone track update — Bay of Bengal (Cat. 2)', tag: 'Disaster', tagClass: 'tag-d', time: '3h ago' },
  { color: '#f4a832', text: 'Poverty index updated — 8 districts, Mozambique', tag: 'Poverty', tagClass: 'tag-p', time: '5h ago' },
];

export default function IntelligenceFeed() {
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Intelligence Feed</span>
        <span className="panel-meta">Live · 60s refresh</span>
      </div>
      <div className="feed-scroll">
        {feedItems.map((item, i) => (
          <div key={i} className="feed-item">
            <div className="feed-dot" style={{ background: item.color }} />
            <div>
              <div className="feed-text">{item.text}</div>
              <div className="feed-sub">
                <span className={`tag ${item.tagClass}`}>{item.tag}</span>
                <span>{item.time}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
