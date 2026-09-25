/**
 * Shell for the published legal texts (/privacy, /terms). Laid out like the
 * company's official documents — centred logo, green rule, registered name
 * and RC number, serif body — because these are the company's commitments,
 * not dashboard UI. The text itself is generated from docs/legal/*.md by
 * docs/legal/build_legal_pages.py; it is our own approved copy, never user
 * input, which is why it is set as HTML.
 */
import Link from 'next/link';

export default function LegalPage({
  title,
  updated,
  html,
}: {
  title: string;
  updated: string;
  html: string;
}) {
  return (
    <div className="legal">
      <header className="legal-head">
        <Link href="/" className="legal-logo-link" aria-label="Bizra Farms Integrated — home">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/bizra-assets/bizra-logo.jpg" alt="Bizra Farms Integrated" className="legal-logo" />
        </Link>
        <div className="legal-rule" />
        <div className="legal-company">BIZRA FARMS INTEGRATED NIGERIA LIMITED</div>
        <div className="legal-rc">(RC 1929412)</div>
      </header>

      <main className="legal-body">
        <p className="legal-kicker">EconomicBridge</p>
        <h1>{title}</h1>
        <p className="legal-updated">{updated}</p>
        <article dangerouslySetInnerHTML={{ __html: html }} />
      </main>

      <footer className="legal-foot">
        <nav aria-label="Legal and site links">
          <Link href="/privacy">Privacy Notice</Link>
          <Link href="/terms">Terms of Use</Link>
          <Link href="/landing">EconomicBridge</Link>
          <Link href="/">Bizra Farms Integrated</Link>
        </nav>
        <p>
          Bizra Farms Integrated Nigeria Limited · RC 1929412 · Kebbi State, Nigeria ·{' '}
          <a href="mailto:bizra@economicbridge.org">bizra@economicbridge.org</a>
        </p>
      </footer>
    </div>
  );
}
