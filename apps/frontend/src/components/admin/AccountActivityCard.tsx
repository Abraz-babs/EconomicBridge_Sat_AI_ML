'use client';

import { useState } from 'react';

import { setViewAs } from '@/hooks/useViewAs';
import {
  useAccountActivity,
  useAccountDetail,
  type AccountSummary,
} from '@/hooks/useAccountActivity';

const WINDOWS = [7, 30, 90] as const;

/** Below this an account has signed in but done essentially nothing. */
const BARELY_USED_REQUESTS = 20;

/**
 * Super-admin: what every account actually does with the platform.
 *
 * Read activity is invisible to the audit log, which records mutations only —
 * and partner/government accounts almost never mutate. This reads the usage
 * rollup instead (services/activity.py), so an account that signs in and
 * browses shows up honestly.
 */
export default function AccountActivityCard() {
  const [days, setDays] = useState<number>(30);
  const [openId, setOpenId] = useState<string | null>(null);
  const { data, isLoading, isError } = useAccountActivity(days);

  function startViewAs(a: AccountSummary) {
    if (!a.org_slug) return;
    setViewAs({ orgSlug: a.org_slug, label: a.org_name ?? a.email });
  }

  const accounts = data?.accounts ?? [];
  const active = accounts.filter((a) => a.requests > 0).length;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Account Activity</span>
        <span className="panel-meta">
          {isError
            ? 'API unreachable'
            : `${active} of ${accounts.length} active · last ${days} days`}
        </span>
      </div>
      <div className="upload-body">
        <p className="upload-desc">
          Usage per account — sign-ins, requests, and which modules and tenants
          they opened. Counted from authenticated API calls; the public overview
          is anonymous and is not attributed to anyone.
        </p>

        <div className="aa-windows" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              className={`aa-window${w === days ? ' is-active' : ''}`}
              aria-pressed={w === days}
              onClick={() => setDays(w)}
            >
              {w} days
            </button>
          ))}
        </div>

        {isLoading && <p className="upload-desc">Loading…</p>}
        {!isLoading && accounts.length === 0 && (
          <p className="upload-desc">No accounts yet.</p>
        )}

        {accounts.length > 0 && (
          <div className="tr-matrix-wrap">
            <table className="tr-matrix aa-table">
              <thead>
                <tr>
                  <th className="tr-sticky">Account</th>
                  <th>Sign-ins</th>
                  <th>Requests</th>
                  <th>Active days</th>
                  <th>Last seen</th>
                  <th>Modules used</th>
                  <th>Reproduce</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <AccountRow
                    key={a.user_id}
                    account={a}
                    days={days}
                    open={openId === a.user_id}
                    onToggle={() =>
                      setOpenId(openId === a.user_id ? null : a.user_id)}
                    onViewAs={startViewAs}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function AccountRow({
  account, days, open, onToggle, onViewAs,
}: {
  account: AccountSummary;
  days: number;
  open: boolean;
  onToggle: () => void;
  onViewAs: (a: AccountSummary) => void;
}) {
  const a = account;
  return (
    <>
      <tr className={open ? 'aa-row is-open' : 'aa-row'}>
        <td className="tr-sticky">
          <button type="button" className="aa-expand" onClick={onToggle}
                  aria-expanded={open}>
            <span className="aa-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
            <span className="tr-name">{a.full_name || a.email}</span>
          </button>
          <span className="tr-sub">
            {a.org_name ?? 'no organisation'} · {a.role}
            {!a.is_active && ' · not activated'}
          </span>
        </td>
        <td className="aa-num">{a.logins}</td>
        <td className="aa-num">{a.requests.toLocaleString()}</td>
        <td className="aa-num">{a.active_days}</td>
        <td>{describeLastSeen(a)}</td>
        <td>
          {a.modules.length === 0
            ? <span className="aa-quiet">—</span>
            : a.modules.map((m) => <span key={m} className="aa-chip">{m}</span>)}
        </td>
        <td>
          {a.org_slug
            ? (
              <button
                type="button"
                className="aa-viewas"
                onClick={() => onViewAs(a)}
                title="Show the dashboard with this account's module access"
              >
                View as
              </button>
            )
            : <span className="aa-quiet" title="No organisation to simulate">—</span>}
        </td>
      </tr>
      {open && (
        <tr className="aa-detail-row">
          <td colSpan={7}><AccountDetailPanel userId={a.user_id} days={days} /></td>
        </tr>
      )}
    </>
  );
}

function AccountDetailPanel({ userId, days }: { userId: string; days: number }) {
  const { data, isLoading } = useAccountDetail(userId, days);
  if (isLoading) return <p className="upload-desc">Loading…</p>;
  if (!data) return <p className="upload-desc">No detail available.</p>;

  const peak = Math.max(1, ...data.daily.map((d) => d.requests));

  return (
    <div className="aa-detail">
      <div className="aa-detail-col">
        <h4 className="aa-detail-title">Daily requests</h4>
        {data.daily.length === 0
          ? <p className="aa-quiet">No activity in this window.</p>
          : (
            <div className="aa-spark" role="img"
                 aria-label={`Daily request counts over ${days} days`}>
              {data.daily.map((d) => (
                <span
                  key={d.day}
                  className="aa-bar"
                  style={{ height: `${Math.round((d.requests / peak) * 100)}%` }}
                  title={`${d.day}: ${d.requests} requests`}
                />
              ))}
            </div>
          )}
      </div>

      <div className="aa-detail-col">
        <h4 className="aa-detail-title">Tenants opened</h4>
        {data.by_tenant.length === 0
          ? <p className="aa-quiet">None.</p>
          : (
            <ul className="aa-list">
              {data.by_tenant.map((t) => (
                <li key={t.name}>
                  <span>{t.name}</span><span className="aa-num">{t.requests}</span>
                </li>
              ))}
            </ul>
          )}
      </div>

      <div className="aa-detail-col">
        <h4 className="aa-detail-title">Recent sign-ins</h4>
        {data.logins.length === 0
          ? <p className="aa-quiet">Never signed in.</p>
          : (
            <ul className="aa-list">
              {data.logins.slice(0, 8).map((l) => (
                <li key={`${l.at}-${l.ip_address ?? ''}`}>
                  <span>{new Date(l.at).toLocaleString()}</span>
                  <span className="aa-quiet">{l.ip_address ?? '—'}</span>
                </li>
              ))}
            </ul>
          )}
      </div>
    </div>
  );
}

/**
 * "Last seen" prefers the activity counter but falls back to the login
 * timestamp: an account can sign in and read nothing but the public overview,
 * which is not counted. Reporting "never" for someone who signed in this
 * morning would be worse than imprecise — it would be wrong.
 */
function describeLastSeen(a: AccountSummary): string {
  const stamp = a.last_seen ?? a.last_login_at;
  if (!stamp) return 'never signed in';
  const when = new Date(stamp);
  const hours = (Date.now() - when.getTime()) / 36e5;
  if (hours < 1) return 'just now';
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const label = `${Math.floor(hours / 24)}d ago`;
  return a.requests < BARELY_USED_REQUESTS && a.logins > 0
    ? `${label} (barely used)`
    : label;
}
