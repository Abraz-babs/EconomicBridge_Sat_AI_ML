'use client';

/**
 * Your access — computed from the real account, the rules the API enforces.
 *
 * View and Reports follow the organisation's plan (tenant_modules, enforced by
 * the API's module-access middleware); Download is the platform operator's
 * alone (require_super_admin on every export). Visitors see the Overview only.
 * Until 2026-09-29 this table was a fixed matrix per demo persona.
 */

import { useRole } from '@/context/RoleContext';
import { ACCESS_MODULES, matrixHeaders } from '@/data/roles';
import { useEffectiveModules } from '@/hooks/useEffectiveModules';

export default function DataAccessMatrix() {
  const { roleConfig } = useRole();
  const { modules } = useEffectiveModules();
  const kind = roleConfig.kind;
  const operator = kind === 'operator';

  const canView = (key: string): boolean | null => {
    if (kind === 'visitor') return false;
    if (operator) return true;
    if (modules === undefined) return null;          // still loading
    return modules.includes(key);
  };

  const cellClass = (v: boolean | null) => (v === null ? 'partial' : v ? 'check' : 'cross');
  const mark = (v: boolean | null) => (v === null ? '…' : v ? '✓' : '—');

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Your Access</span>
        <span className="panel-meta">{roleConfig.label}</span>
      </div>
      <table className="matrix-table">
        <thead>
          <tr>
            {matrixHeaders.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ACCESS_MODULES.map((m) => {
            const v = canView(m.key);
            return (
              <tr key={m.key}>
                <td>{m.label}</td>
                <td className={cellClass(v)}>{mark(v)}</td>
                <td className={cellClass(v)}>{mark(v)}</td>
                <td className={operator ? 'check' : 'cross'}>{operator ? '✓' : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="matrix-note">
        {kind === 'visitor'
          ? 'Sign in to open modules. Plans are set per organisation.'
          : operator
            ? 'Platform operator: every module, report and download.'
            : '— not in your plan. Data files are prepared by EconomicBridge on request.'}
      </div>
    </div>
  );
}
