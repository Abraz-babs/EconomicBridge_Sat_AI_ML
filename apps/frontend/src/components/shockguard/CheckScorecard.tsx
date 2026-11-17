'use client';

/**
 * How far ahead the forecast holds: every score by the number of days before
 * the day it was made, physics and AI models side by side, over the season or
 * the last 30 days. Then the ensemble's chances against what happened. Built on
 * the 15-day outlook's grid, so the two read alike.
 */

import { useState, type ReactNode } from 'react';

import type { CheckModel, Counts, ForecastCheck } from '@/hooks/useForecastCheck';
import {
  brierSkill, calibration, caught, confirmed, ets, heavyCaught, heavyConfirmed, MODEL_COL, pctText, signed, totalBias,
  typicalMiss, wetShare, type CalPoint, type Ratio,
} from './checkModel';
import { dayMonth, mm } from './forecastModel';

const LEADS = Array.from({ length: 15 }, (_, k) => k);
const BAR_PX = 64;
const MODELS: CheckModel[] = ['ifs', 'aifs'];

function Pair({ ratios }: { ratios: (Ratio | null)[] }) {
  return (
    <>
      <em>{ratios.map((r, i) => <span key={MODELS[i]} className={`ck-v ck-v--${MODELS[i]}`}>{r ? pctText(r) : '—'}</span>)}</em>
      {ratios.map((r, i) => (
        <i key={MODELS[i]} className={MODELS[i]} style={{ height: `${r?.pct ? (r.pct / 100) * BAR_PX : 0}px` }}
          title={r ? `${r.num} of ${r.den}` : 'no pairs'} />
      ))}
    </>
  );
}

type At = (m: CheckModel, k: number) => Counts | null;

function Row({ label, sub, tall, children }: { label: string; sub: string; tall?: boolean; children: (k: number) => ReactNode }) {
  return (
    <>
      <div className="og-lab"><b>{label}</b>{sub}</div>
      {LEADS.map((k) => (
        <div key={k} className={`og-c ${tall ? 'og-rain ck-pair' : 'ck-num'}${k >= 10 ? ' is-outlook' : ''}`}>{children(k)}</div>
      ))}
    </>
  );
}

function PairRow({ label, sub, at, f }: { label: string; sub: string; at: At; f: (c: Counts) => Ratio }) {
  return (
    <Row tall label={label} sub={sub}>
      {(k) => <Pair ratios={MODELS.map((m) => { const c = at(m, k); return c ? f(c) : null; })} />}
    </Row>
  );
}

function NumRow({ label, sub, at, f, models = MODELS }: {
  label: string; sub: string; at: At; f: (c: Counts) => string; models?: CheckModel[];
}) {
  return (
    <Row label={label} sub={sub}>
      {(k) => (
        <em>
          {models.map((m) => {
            const c = at(m, k);
            return <span key={m} className={models.length > 1 ? `ck-v ck-v--${m}` : 'ck-v'}>{c ? f(c) : '—'}</span>;
          })}
        </em>
      )}
    </Row>
  );
}

function CalChart({ title, points, near, far }: { title: string; points: Record<string, CalPoint[]>; near: string; far: string }) {
  const W = 240;
  const H = 200;
  const P = 28;
  const x = (v: number) => P + (v / 100) * (W - P - 8);
  const y = (v: number) => H - P - (v / 100) * (H - P - 8);
  const line = (ps: CalPoint[]) => ps.map((p, i) => `${i ? 'L' : 'M'}${x(p.said).toFixed(1)},${y(p.got).toFixed(1)}`).join(' ');
  return (
    <figure className="ck-cal-fig">
      <figcaption>{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: chance the ensemble gave against the share of the area that got the rain`}>
        {[0, 50, 100].map((v) => (
          <g key={v}>
            <line x1={x(v)} x2={x(v)} y1={y(0)} y2={y(100)} className="ck-grid" />
            <line x1={x(0)} x2={x(100)} y1={y(v)} y2={y(v)} className="ck-grid" />
            <text x={x(v)} y={H - 10} className="ck-ax" textAnchor="middle">{v}%</text>
            <text x={P - 5} y={y(v) + 3} className="ck-ax" textAnchor="end">{v}%</text>
          </g>
        ))}
        <line x1={x(0)} y1={y(0)} x2={x(100)} y2={y(100)} className="ck-diag" />
        {[far, near].map((g) => (
          <g key={g} className={g === near ? 'ck-near' : 'ck-far'}>
            <path d={line(points[g] ?? [])} fill="none" />
            {(points[g] ?? []).map((p) => (
              <circle key={p.lo} cx={x(p.said)} cy={y(p.got)} r={Math.min(7, 2.5 + Math.sqrt(p.n) / 12)}>
                <title>{`${p.lo}–${p.hi}%: said ${Math.round(p.said)}% on average, ${Math.round(p.got)}% of the area got it (${p.n.toLocaleString('en-GB')} pairs)`}</title>
              </circle>
            ))}
          </g>
        ))}
      </svg>
    </figure>
  );
}

export default function CheckScorecard({ s, unit }: { s: ForecastCheck; unit: string }) {
  const [win, setWin] = useState<'all' | 'recent'>('all');
  const sc = s.scorecard[win] ?? {};
  const at: At = (m, k) => sc[m]?.[k] ?? null;
  const [near, , far] = s.chance_groups;
  const pts = (t: number) => Object.fromEntries(s.chance_groups.map((g) => [g, calibration(s.chances[String(t)], g, s.chance_bins)]));
  const skill1 = brierSkill(s.chances['1']);
  const from = win === 'all' ? s.first_day : s.recent_from;
  const base = at('ifs', 1);
  const two = (v: number | null): string => (v === null ? '—' : v.toFixed(2));

  return (
    <div className="fc-outlook ck-score" id="ck-score">
      <div className="fc-outlook-head">
        <div>
          <h3 className="sgr-h2">How far ahead the forecast holds</h3>
          <div className="fc-outlook-title">
            {from ? `${dayMonth(from)} – ${dayMonth(s.last_day ?? from)}` : ''} · every {unit}, every day
          </div>
        </div>
        <div className="ck-head-side">
          <div className="fc-mode" role="group" aria-label="Scorecard window">
            <button type="button" aria-pressed={win === 'all'} onClick={() => setWin('all')}>Season</button>
            <button type="button" aria-pressed={win === 'recent'} onClick={() => setWin('recent')}>Last {s.recent_days} days</button>
          </div>
          <div className="fc-key" aria-hidden="true">
            <span><i style={{ background: MODEL_COL.ifs }} />Physics model (IFS)</span>
            <span><i style={{ background: MODEL_COL.aifs }} />AI model (AIFS)</span>
          </div>
        </div>
      </div>
      <p className="fc-outlook-sum">
        Columns: how many days before the day the forecast was made — 0 is the run published that morning. A rain day is 1 mm or more
        averaged over the {unit}; a soaking day 10 mm or more. “Caught”: of the days NASA’s satellites measured rain, the share the
        forecast had called. “Confirmed”: of the forecast’s rain calls, the share the satellites measured. Hover a bar for its count.
      </p>
      {base && (
        <p className="fc-outlook-sum ck-base">
          Read those against the season: rain fell on {pctText(wetShare(base))} of {unit}-days here, so a forecast of rain every day
          would catch every rain day and be confirmed {pctText(wetShare(base))} of the time. “Skill beyond chance” takes that luck
          out — the equitable threat score, where 0 is no better than chance and 1 is perfect.
        </p>
      )}
      <div className="og-scroll">
        <div className="og ck-og" role="table" aria-label="Forecast check by days ahead">
          <div className="og-lab"><b>Made … days before</b>the day it was for</div>
          {LEADS.map((k) => (
            <div key={k} className={`og-h og-c${k >= 10 ? ' is-outlook' : ''}`}>{k === 0 ? 'same day' : 'before'}<b>{k}</b></div>
          ))}
          <PairRow label="Rain days caught" sub="measured 1 mm+, forecast had it" at={at} f={caught} />
          <PairRow label="Rain calls confirmed" sub="forecast 1 mm+, satellites had it" at={at} f={confirmed} />
          <NumRow label="Skill beyond chance" sub="rain days · 0 = chance, 1 = perfect" at={at} f={(c) => two(ets(c))} />
          <NumRow label="Soaking days caught" sub="measured 10 mm+" at={at} f={(c) => pctText(heavyCaught(c))} />
          <NumRow label="Soaking calls confirmed" sub="forecast 10 mm+" at={at} f={(c) => pctText(heavyConfirmed(c))} />
          <NumRow label="Skill beyond chance" sub="soaking days" at={at} f={(c) => two(ets(c, true))} />
          <NumRow label="Rain total vs measured" sub="+ = forecast wetter" at={at} f={(c) => signed(totalBias(c))} />
          <NumRow label="Typical miss" sub="mm, on days either had rain" at={at}
            f={(c) => { const v = typicalMiss(c); return v === null ? '—' : mm(v); }} />
          <NumRow label="Rain days measured" sub="the sample behind each column" at={at} models={['ifs']}
            f={(c) => (c[0] + c[2]).toLocaleString('en-GB')} />
        </div>
      </div>

      <div className="ck-cal">
        <div className="ck-cal-text">
          <h3 className="sgr-h2">Are the ensemble’s chances honest?</h3>
          <p className="fc-outlook-sum">
            When ECMWF’s ensemble gives a chance of rain, that is the share of the {unit} it expects to get it. Each point sets the chance it
            gave (across) against the share of the {unit} NASA’s satellites measured with that rain (up). On the diagonal, the chances
            mean what they say; below it, rain came less often than the ensemble said. Season record; points with under 30 pairs are left out.
          </p>
          <p className="fc-listnote">
            <i className="ck-key ck-key--near" /> forecasts made {near?.replace('-', '–')} days before ·{' '}
            <i className="ck-key ck-key--far" /> made {far?.replace('-', '–')} days before
          </p>
          {skill1.length > 0 && (
            <p className="fc-listnote">
              Brier skill for a wet day against always saying the usual share (+ is better, 0 is no better):{' '}
              {skill1.map((v, k) => `${k}d ${v === null ? '—' : v.toFixed(2)}`).join(' · ')}
            </p>
          )}
        </div>
        <CalChart title="Chance of a wet day (1 mm+)" points={pts(1)} near={near} far={far} />
        <CalChart title="Chance of a soaking day (10 mm+)" points={pts(10)} near={near} far={far} />
      </div>
    </div>
  );
}
