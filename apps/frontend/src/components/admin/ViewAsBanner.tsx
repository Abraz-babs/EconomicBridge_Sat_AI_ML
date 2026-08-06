'use client';

import { useAuth } from '@/context/AuthContext';
import { clearViewAs, useViewAs } from '@/hooks/useViewAs';

/**
 * Persistent reminder that the dashboard is showing someone else's view.
 *
 * A simulated view that looks identical to the real one is a trap: the
 * operator forgets, sees a padlock, and reports a bug that doesn't exist. So
 * the banner stays on screen for the whole simulation and the way out is
 * always one click.
 */
export default function ViewAsBanner() {
  const { isSuperAdmin } = useAuth();
  const viewAs = useViewAs();

  if (!isSuperAdmin || !viewAs) return null;

  return (
    <div className="viewas-banner" role="status">
      <span className="viewas-dot" aria-hidden="true" />
      <span>
        Viewing the dashboard as <strong>{viewAs.label}</strong> — module access
        matches their plan. Their data is unchanged and nothing is being done on
        their behalf.
      </span>
      <button type="button" className="viewas-exit" onClick={clearViewAs}>
        Exit
      </button>
    </div>
  );
}
