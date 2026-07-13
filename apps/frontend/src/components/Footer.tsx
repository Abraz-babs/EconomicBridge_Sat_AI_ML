export default function Footer() {
  return (
    <footer className="app-footer" role="contentinfo">
      <div className="footer-row">
        <div className="footer-left">
          <span className="footer-brand">ECONOMICBRIDGE v0.3</span>
          <span className="footer-sep">·</span>
          <span>BIZRA FARMS INTEGRATED NIGERIA LIMITED</span>
          <span className="footer-sep">·</span>
          <span className="footer-phase">PRODUCTION · 2026</span>
        </div>
        <div className="footer-center">
          <span>Satellite: ESA Copernicus · NASA FIRMS · N2YO Live Pass · VIIRS · MODIS</span>
        </div>
        <div className="footer-right">
          <span>AI: Conflict Predictor · NDVI Analysis · SAR Processing</span>
          <span className="footer-sep">·</span>
          <span className="footer-ndpa">NDPA 2023</span>
        </div>
      </div>
    </footer>
  );
}
