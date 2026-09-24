'use client';

import { useMemo, useState } from 'react';

import {
  useAlertRecord,
  type RecordEntry,
  type RecordEntryStatus,
} from '@/hooks/useFarmlandAlerts';
import FieldDirections, { GRID3_CREDIT } from '@/components/common/FieldDirections';

/**
 * Alert record — fills the map column under the Alert Spotlight.
 *
 * The active list beside the map is the PRESENT and is untouched. This is the
 * past as well: every alert the platform raised for the tenant, by year and
 * month — radar watches grouped into episodes (one row per continuing watch,
 * not one per daily read), land-change scans, and alerts an officer closed.
 * "Show on map" hands an entry to the panel, which rings it on the map and
 * opens it in the existing Spotlight like any live alert.
 *
 * Nothing is inferred here; every figure comes from GET /farmland/record.
 */

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];

// ALERT_THRESHOLD in the ingestion service's encroachment detector (default).
const ALERT_BAR = 0.3;

const STATUS_LABEL: Record<RecordEntryStatus, string> = {
  active: 'Active now',
  ended: 'Ended',
  resolved: 'Resolved by officer',
  acknowledged: 'Acknowledged',
  dismissed: 'Dismissed by officer',
  superseded: 'Replaced by later scan',
};

type Filter = 'all' | 'past' | 'radar' | 'land' | 'officer';
const FILTERS: [Filter, string][] = [
  ['all', 'All'],
  ['past', 'Past only'],
  ['radar', 'Radar watches'],
  ['land', 'Land change'],
  ['officer', 'Officer-actioned'],
];

const isOfficer = (e: RecordEntry) => e.kind === 'officer_closed';

function day(s: string): string {
  const [, m, d] = s.split('-').map(Number);
  return `${d} ${MON[m - 1]}`;
}
const dayYear = (s: string) => `${day(s)} ${s.slice(0, 4)}`;

export function recordKey(e: RecordEntry): string {
  return `${e.kind}:${e.lga ?? ''}:${e.start}:${e.end}:${e.status}`;
}

function matches(e: RecordEntry, filter: Filter): boolean {
  switch (filter) {
    case 'past': return e.status !== 'active';
    case 'radar': return e.kind === 'radar_watch';
    case 'land': return e.kind === 'land_change_scan';
    case 'officer': return isOfficer(e);
    default: return true;
  }
}

/** Score at each read against the alert bar (dashed line). */
function ReadLine({ reads }: { reads: RecordEntry['reads'] }) {
  const scores = reads.map((r) => r.score).filter((v): v is number => v != null);
  if (scores.length === 0) return <span />;
  const W = 92, H = 24, top = 0.7;
  const y = (v: number) => H - 3 - (Math.min(v, top) / top) * (H - 6);
  const x = (i: number) => (scores.length === 1 ? W / 2 : 4 + i * ((W - 8) / (scores.length - 1)));
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Score at each read: ${scores.map((s) => s.toFixed(2)).join(', ')}; alert bar ${ALERT_BAR.toFixed(2)}`}>
      <line x1={0} x2={W} y1={y(ALERT_BAR)} y2={y(ALERT_BAR)} stroke="#b0aa9f" strokeDasharray="2 2" strokeWidth={1} />
      {scores.length > 1 && (
        <polyline points={scores.map((v, i) => `${x(i)},${y(v)}`).join(' ')} fill="none" stroke="#c1440e" strokeWidth={1.4} />
      )}
      {scores.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r={2.3} fill="#c1440e" />)}
    </svg>
  );
}

function describe(e: RecordEntry): { title: string; line: string } {
  if (e.kind === 'land_change_scan') {
    const tail = e.status === 'superseded'
      ? ' A later scan replaced them; they are kept here.'
      : ' All are on the live list.';
    return {
      title: `Land-change scan · ${e.lgas ?? 0} LGA${e.lgas === 1 ? '' : 's'}`,
      line: `${e.patches ?? 0} patches that greened in the two seasons before and stayed bare, each at its own coordinates. Read ${dayYear(e.start)}.${tail}`,
    };
  }
  if (isOfficer(e)) {
    return {
      title: `${e.lga ?? 'Unknown'} LGA`,
      line: `${e.summary ?? 'Alert'} · raised ${dayYear(e.start)} · closed ${dayYear(e.end)}`,
    };
  }
  const span = e.start === e.end ? dayYear(e.start) : `${day(e.start)} → ${dayYear(e.end)}`;
  const n = e.reads.length;
  return {
    title: `${e.lga ?? 'Unknown'} LGA`,
    line: `Radar watch · ${span} · ${n} read${n === 1 ? '' : 's'}`
      + (e.peak_sigma != null ? ` · peak ${e.peak_sigma}σ` : '')
      + (e.status === 'ended' ? ' · calm at its next read' : ''),
  };
}

interface Props {
  tenantId: string;
  stateLabel: string;
  /** Key of the entry currently revisited on the map (highlighted). */
  focusedKey: string | null;
  onRevisit: (entry: RecordEntry, key: string) => void;
}

export default function AlertRecord({ tenantId, stateLabel, focusedKey, onRevisit }: Props) {
  const [year, setYear] = useState<number | undefined>(undefined);
  const [month, setMonth] = useState<string>('all');
  const [filter, setFilter] = useState<Filter>('all');
  const query = useAlertRecord(tenantId, year);
  const record = query.data;

  const entries = useMemo(() => record?.entries ?? [], [record]);
  const months = useMemo(
    () => Array.from(new Set(entries.map((e) => e.start.slice(0, 7)))).sort().reverse(),
    [entries],
  );
  const shown = useMemo(
    () => entries.filter((e) => (month === 'all' || e.start.startsWith(month)) && matches(e, filter)),
    [entries, month, filter],
  );
  const groups = useMemo(() => {
    const g = new Map<string, RecordEntry[]>();
    for (const e of shown) {
      const m = e.start.slice(0, 7);
      g.set(m, [...(g.get(m) ?? []), e]);
    }
    return Array.from(g.entries());
  }, [shown]);

  const counts = useMemo(() => {
    const c = { active: 0, ended: 0, officer: 0, superseded: 0 };
    for (const e of entries) {
      if (isOfficer(e)) c.officer += 1;
      else if (e.status === 'active') c.active += 1;
      else if (e.status === 'superseded') c.superseded += 1;
      else c.ended += 1;
    }
    return c;
  }, [entries]);

  return (
    <section className="fp-record" aria-labelledby="fp-record-title">
      <div className="fp-record-head">
        <span id="fp-record-title">Alert record — {stateLabel}</span>
        {record && record.years.length > 0 && (
          <label className="fp-record-year">
            Year
            <select
              value={record.year ?? ''}
              onChange={(ev) => { setYear(Number(ev.target.value)); setMonth('all'); }}
            >
              {record.years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
        )}
      </div>

      {query.isLoading && <div className="fp-alert-empty">Loading the record…</div>}
      {query.isError && (
        <div className="fp-alert-error">The record could not be loaded. The live list above is unaffected; refresh to try again.</div>
      )}

      {record && (
        <>
          {entries.length > 0 && (
            <>
              <div className="fp-record-tools" role="group" aria-label="Month">
                <button type="button" className={`fp-layer-btn ${month === 'all' ? 'active' : ''}`}
                  aria-pressed={month === 'all'} onClick={() => setMonth('all')}>All months</button>
                {months.map((m) => (
                  <button key={m} type="button" className={`fp-layer-btn ${month === m ? 'active' : ''}`}
                    aria-pressed={month === m} onClick={() => setMonth(m)}>
                    {MON[Number(m.slice(5)) - 1]} {m.slice(0, 4)}
                  </button>
                ))}
              </div>
              <div className="fp-record-tools" role="group" aria-label="Kind">
                {FILTERS.map(([k, label]) => (
                  <button key={k} type="button" className={`fp-layer-btn ${filter === k ? 'active' : ''}`}
                    aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
                ))}
              </div>
            </>
          )}

          <div className="fp-record-summary">
            {entries.length > 0 ? (
              <>
                <b>{entries.length}</b> entr{entries.length === 1 ? 'y' : 'ies'} in {record.year}:{' '}
                {counts.active} still active, {counts.ended} ended, {counts.officer} closed by an officer
                {counts.superseded ? `, ${counts.superseded} replaced by a later scan` : ''}.
                {record.watches_kept_since && (
                  <> Radar watches kept since <b>{dayYear(record.watches_kept_since)}</b>; earlier ones were not kept, so the record fills forward from there.</>
                )}
                {entries.some((e) => e.nearest_place) && <> {GRID3_CREDIT}.</>}
              </>
            ) : (
              <>No entries yet for {stateLabel}. The first alert raised here will start the record, and it will stay here.</>
            )}
          </div>

          {entries.length > 0 && shown.length === 0 && (
            <div className="fp-alert-empty">Nothing in this view. Try All months or All.</div>
          )}

          <div className="eb-scroll fp-record-scroll">
          {groups.map(([m, list]) => (
            <div key={m}>
              <div className="fp-record-month">
                <span>{MONTH[Number(m.slice(5)) - 1]} {m.slice(0, 4)}</span>
                <span>{list.length} entr{list.length === 1 ? 'y' : 'ies'}</span>
              </div>
              {list.map((e) => {
                const key = recordKey(e);
                const { title, line } = describe(e);
                const canShow = Boolean(e.location) || e.points.length > 0;
                return (
                  <div key={key}
                    className={`fp-record-entry fp-record-entry--${e.status}${focusedKey === key ? ' is-focused' : ''}`}>
                    <div className="fp-record-stripe" />
                    <div className="fp-record-body">
                      <div className="fp-alert-top">
                        <span className="fp-alert-location">{title}</span>
                        <span className={`fp-record-chip fp-record-chip--${e.status}`}>{STATUS_LABEL[e.status]}</span>
                      </div>
                      <div className="fp-alert-desc">{line}</div>
                      {e.location && (
                        <FieldDirections place={e.nearest_place} lat={e.location.lat} lon={e.location.lon} />
                      )}
                      <div className="fp-record-foot">
                        {e.kind === 'radar_watch' && <ReadLine reads={e.reads} />}
                        <span className="fp-alert-meta fp-record-meta">
                          {e.affected_area_ha != null && <span>~{Math.round(e.affected_area_ha)} ha</span>}
                          {e.livelihoods_at_risk != null && <span>{e.livelihoods_at_risk.toLocaleString()} livelihoods</span>}
                          {e.peak_score != null && <span>score {e.peak_score.toFixed(2)} / {ALERT_BAR.toFixed(2)}</span>}
                        </span>
                        {canShow && (
                          <button type="button" className="fp-resolve-btn" onClick={() => onRevisit(e, key)}>
                            Show on map
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
          </div>
        </>
      )}
    </section>
  );
}
