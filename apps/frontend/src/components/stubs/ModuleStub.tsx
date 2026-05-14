interface ModuleStubProps {
  num: string;
  title: string;
  description: string;
  dataSources?: string[];
  quarter?: string;
  quarterLabel?: string;
  capabilities?: string[];
}

export default function ModuleStub({
  num,
  title,
  description,
  dataSources = [],
  quarter = 'TBD',
  quarterLabel = 'Roadmap',
  capabilities = [],
}: ModuleStubProps) {
  return (
    <div className="panel anim a1" role="region" aria-label={`${title} module preview`}>
      <div className="ms-container">
        {/* Left Column — Info */}
        <div className="ms-info">
          <div className="ms-badge-row">
            <span className="ms-num">MODULE {num}</span>
            <span className="ms-quarter">{quarter}</span>
          </div>
          <h2 className="ms-title">{title}</h2>
          <p className="ms-desc">{description}</p>

          {dataSources.length > 0 && (
            <div className="ms-sources">
              <span className="ms-sources-label">Data Sources</span>
              <div className="ms-source-tags">
                {dataSources.map((src) => (
                  <span key={src} className="ms-source-tag">{src}</span>
                ))}
              </div>
            </div>
          )}

          {capabilities.length > 0 && (
            <div className="ms-capabilities">
              <span className="ms-sources-label">Capabilities</span>
              <ul className="ms-cap-list">
                {capabilities.map((cap) => (
                  <li key={cap} className="ms-cap-item">
                    <span className="ms-cap-check">✓</span>
                    {cap}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Right Column — Visual */}
        <div className="ms-visual">
          <div className="ms-num-large">{num}</div>
          <div className="ms-status-badge">
            <div className="ms-status-dot" />
            {quarterLabel}
          </div>
          <div className="ms-architecture-note">
            Per EconomicBridge Architecture v2.0
          </div>
        </div>
      </div>
    </div>
  );
}
