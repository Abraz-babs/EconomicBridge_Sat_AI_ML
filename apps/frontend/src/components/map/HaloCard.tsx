'use client';

/**
 * The card a clicked halo opens: what the point is, one headline number, the
 * real figures behind it with their sources, and a plain "what this means".
 * Rendered by EBMap next to the point it belongs to (operator's standing rule,
 * 2026-09-26: "any pointed halo should show deep stats and explanation").
 */

import type { ReactNode } from 'react';

export interface HaloCardRow {
  k: string;
  v: ReactNode;
}

export interface HaloCardProps {
  title: string;
  big?: string;
  rows: HaloCardRow[];
  why?: string;
  /** Optional small chart (e.g. a series across rounds). */
  chart?: ReactNode;
  actions?: ReactNode;
  onClose: () => void;
  tone?: 'light' | 'dark';
}

export default function HaloCard(props: HaloCardProps) {
  const { title, big, rows, why, chart, actions, onClose, tone = 'light' } = props;
  return (
    <div className={`mm-card mm-card--${tone}`} role="dialog" aria-label={title}>
      <div className="mm-card-head">
        <span className="mm-card-title">{title}</span>
        <button type="button" className="mm-card-close" aria-label="Close" onClick={onClose}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M2 2L12 12M12 2L2 12" />
          </svg>
        </button>
      </div>
      {big && <div className="mm-card-big">{big}</div>}
      {chart}
      <dl className="mm-card-rows">
        {rows.map((r) => (
          <div key={r.k} className="mm-card-row">
            <dt>{r.k}</dt>
            <dd>{r.v}</dd>
          </div>
        ))}
      </dl>
      {why && <p className="mm-card-why">{why}</p>}
      {actions && <div className="mm-card-actions">{actions}</div>}
    </div>
  );
}
