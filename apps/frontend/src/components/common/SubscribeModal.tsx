'use client';

/**
 * Shown when a signed-in tenant clicks a padlocked (unsubscribed) module in
 * the nav. Corporate, upsell-friendly framing: the module stays visible in
 * the catalogue precisely so tenants can discover and request it — nothing
 * is hidden because it isn't paid for.
 */
export default function SubscribeModal({
  moduleLabel,
  tenantName,
  onClose,
}: {
  moduleLabel: string;
  tenantName: string;
  onClose: () => void;
}) {
  const mailto =
    'mailto:bizra@economicbridge.org' +
    `?subject=${encodeURIComponent(`Module subscription request — ${moduleLabel} (${tenantName})`)}` +
    `&body=${encodeURIComponent(
      `Hello EconomicBridge team,\n\nWe would like to add the ${moduleLabel} module ` +
      `to ${tenantName}'s subscription. Please contact us with the details.\n\nThank you.`,
    )}`;

  return (
    <div
      className="auth-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={`${moduleLabel} — subscription required`}
      onClick={onClose}
    >
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="auth-modal-title">🔒 {moduleLabel}</h2>
        <p className="auth-modal-sub">
          <strong>{moduleLabel}</strong> is not included in {tenantName}&apos;s
          current EconomicBridge subscription.
        </p>
        <p className="auth-modal-sub">
          Your plan covers the modules shown unlocked in the navigation. To add{' '}
          {moduleLabel}, contact our team — activation is typically completed
          within one business day of confirmation.
        </p>
        <p className="auth-modal-sub">
          <strong>bizra@economicbridge.org</strong> · +234 703 791 9465
        </p>
        <div className="auth-modal-actions">
          <button type="button" className="auth-btn auth-btn--ghost" onClick={onClose}>
            Close
          </button>
          <a className="auth-btn auth-btn--go" href={mailto} style={{ textDecoration: 'none' }}>
            Request this module
          </a>
        </div>
      </div>
    </div>
  );
}
