/**
 * Footer — names only what runs today (2026-09-29): the conflict predictor was
 * trained on generated data and is retired; the "SAR U-Net" never shipped.
 */
export default function Footer() {
  return (
    <footer className="app-footer" role="contentinfo">
      <div className="footer-row">
        <div className="footer-left">
          <span className="footer-brand">ECONOMICBRIDGE v1.0</span>
          <span className="footer-sep">·</span>
          <span>BIZRA FARMS INTEGRATED NIGERIA LIMITED</span>
          <span className="footer-sep">·</span>
          <span className="footer-phase">LIVE · 2026</span>
        </div>
        <div className="footer-center">
          <span>Data: Copernicus Sentinel-1 &amp; 2 · NASA FIRMS · NASA GPM IMERG · NASA Black Marble · GRID3 · World Bank</span>
        </div>
        <div className="footer-right">
          <span>Analysis: greenness &amp; radar change · storm engine · leaf-disease classifier</span>
          <span className="footer-sep">·</span>
          <span className="footer-ndpa">NDPA 2023</span>
        </div>
      </div>
    </footer>
  );
}
