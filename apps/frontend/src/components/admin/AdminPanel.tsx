const orgs = [
  {
    name: 'CARE International',
    type: 'NGO / Aid Organization',
    perms: [
      { label: 'Poverty View', bg: '#d8f3dc', color: '#2d6a4f' },
      { label: 'Disaster Ops', bg: '#d8f3dc', color: '#2d6a4f' },
      { label: 'Agri Feed', bg: '#d8f3dc', color: '#2d6a4f' },
      { label: 'Reports — Limited', bg: '#fef3dc', color: '#c97d00' },
    ],
  },
  {
    name: 'Federal Ministry — Nigeria',
    type: 'National Government',
    perms: [
      { label: 'Sovereign Data', bg: '#dce8f5', color: '#1d3557' },
      { label: 'Poverty Full', bg: '#dce8f5', color: '#1d3557' },
      { label: 'Disaster Full', bg: '#dce8f5', color: '#1d3557' },
      { label: 'Agri Full', bg: '#dce8f5', color: '#1d3557' },
      { label: 'Policy Reports', bg: '#dce8f5', color: '#1d3557' },
    ],
  },
  {
    name: 'OCHA / UN Humanitarian',
    type: 'International Body',
    perms: [
      { label: 'Cross-Border', bg: '#f0d9ec', color: '#6b2d5e' },
      { label: 'All Regions', bg: '#f0d9ec', color: '#6b2d5e' },
      { label: 'Raw Data Export', bg: '#f0d9ec', color: '#6b2d5e' },
      { label: 'API Access', bg: '#f0d9ec', color: '#6b2d5e' },
    ],
  },
  {
    name: 'MIT Poverty Lab',
    type: 'Research Institution',
    perms: [
      { label: 'Anonymised Data', bg: '#fef3dc', color: '#7b4f00' },
      { label: 'Historical Archive', bg: '#fef3dc', color: '#7b4f00' },
      { label: 'Model Access', bg: '#fef3dc', color: '#7b4f00' },
      { label: 'No PII', bg: '#fde8e1', color: '#c1440e' },
    ],
  },
];

export default function AdminPanel() {
  return (
    <div className="panel anim a1">
      <div className="panel-header">
        <span className="panel-title">Organisation Permission Manager</span>
        <span className="panel-meta">Admin-controlled access · 12 organisations registered</span>
      </div>
      <div className="admin-grid">
        {orgs.map((org) => (
          <div key={org.name} className="admin-org-card">
            <div className="aorg-name">{org.name}</div>
            <div className="aorg-type">{org.type}</div>
            <div className="aorg-perms">
              {org.perms.map((p) => (
                <span key={p.label} className="aperm" style={{ background: p.bg, color: p.color }}>
                  {p.label}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div style={{ padding: '14px 18px', borderTop: '1px solid var(--border)', fontSize: '10px', color: 'var(--muted)' }}>
        All permission changes are audit-logged. Data sovereignty rules enforced per region. PII access requires DPA agreement on file.
      </div>
    </div>
  );
}
