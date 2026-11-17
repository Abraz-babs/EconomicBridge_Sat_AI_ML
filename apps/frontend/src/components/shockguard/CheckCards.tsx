'use client';

/**
 * The forecast check's KPI strip and its map cards (one day, or the season
 * record of one LGA). Plain counts beside every percentage.
 */

import HaloCard from '@/components/map/HaloCard';
import type { CheckDayArea, CheckLga, CheckModel, ForecastCheck } from '@/hooks/useForecastCheck';
import {
  agreed, caught, confirmed, daySentence, forecastAt, leadLabel, lgaCounts, MODEL_LABEL, MODEL_SHORT, pctText, signed,
  totalBias,
} from './checkModel';
import { dayMonth, mm } from './forecastModel';

const other = (m: CheckModel): CheckModel => (m === 'ifs' ? 'aifs' : 'ifs');
const mmOrDash = (v: number | null | undefined): string => (v === null || v === undefined ? '—' : mm(v));

export function CheckKpis({ s, unit, model, lead, leadIdx }: {
  s: ForecastCheck; unit: string; model: CheckModel; lead: number; leadIdx: number;
}) {
  const c = s.scorecard.all?.[model]?.[lead];
  const o = s.scorecard.all?.[other(model)]?.[lead];
  const last = s.ribbon[s.ribbon.length - 1];
  const lastC = last ? (model === 'ifs' ? last.ifs : last.aifs)[leadIdx] : undefined;
  return (
    <div className="sgr-kpis">
      <div className="sgr-kpi">
        <span className="sgr-kpi-val">{s.days_checked} days</span>
        <span className="sgr-kpi-label">
          {s.lga_days.toLocaleString('en-GB')} {unit}-days measured since {s.first_day ? dayMonth(s.first_day) : '—'}, each set against
          every forecast made for it, up to 14 days before
        </span>
        <span className="sgr-kpi-src">NASA IMERG LATE · ECMWF 00 UTC RUNS</span>
      </div>
      <div className="sgr-kpi">
        <span className="sgr-kpi-val ck-val--hit">{c ? pctText(caught(c)) : '—'}</span>
        <span className="sgr-kpi-label">
          {c ? `of ${(c[0] + c[2]).toLocaleString('en-GB')} rain days measured, the ${MODEL_SHORT[model]} had called from ${leadLabel(lead)}` : 'no rain days measured yet'}
          {o ? ` · ${MODEL_SHORT[other(model)]} ${pctText(caught(o))}` : ''}
        </span>
        <span className="sgr-kpi-src">{MODEL_LABEL[model].toUpperCase()} · RAIN DAYS CAUGHT · 1 MM+</span>
      </div>
      <div className="sgr-kpi">
        <span className="sgr-kpi-val ck-val--confirm">{c ? pctText(confirmed(c)) : '—'}</span>
        <span className="sgr-kpi-label">
          {c ? `of its ${(c[0] + c[1]).toLocaleString('en-GB')} rain calls were confirmed by the satellites` : 'no rain calls yet'}
          {o ? ` · ${MODEL_SHORT[other(model)]} ${pctText(confirmed(o))}` : ''}
          {c && totalBias(c) !== null ? ` · rain total ${signed(totalBias(c))} against measured` : ''}
        </span>
        <span className="sgr-kpi-src">RAIN CALLS CONFIRMED · AGAINST A SATELLITE ESTIMATE</span>
      </div>
      <div className="sgr-kpi">
        <span className="sgr-kpi-val">{last && lastC ? `${lastC[0]} of ${last.wet}` : '—'}</span>
        <span className="sgr-kpi-label">
          {last && lastC
            ? `wet ${unit}s caught on ${dayMonth(last.day)}, the latest day measured · ${lastC[2]} missed · ${lastC[1]} forecast but dry`
            : 'no day measured yet'}
        </span>
        <span className="sgr-kpi-src">LATEST DAY · {MODEL_SHORT[model].toUpperCase()} · MADE {leadLabel(lead).toUpperCase()}</span>
      </div>
    </div>
  );
}

export function CheckDayCard({ a, record, model, lead, leadIdx, day, stateLabel, onClose }: {
  a: CheckDayArea; record: CheckLga | undefined; model: CheckModel; lead: number; leadIdx: number; day: string;
  stateLabel: string; onClose: () => void;
}) {
  const f = forecastAt(a, model, lead);
  const g = forecastAt(a, other(model), lead);
  const r = record ? lgaCounts(record, model, leadIdx) : null;
  const ladder = [0, 1, 3, 7].map((k) => `${k === 0 ? 'same day' : `${k}d`} ${mmOrDash(forecastAt(a, model, k))}`).join(' · ');
  const p1 = lead < 10 ? a.chance_1mm[lead] : undefined;
  return (
    <HaloCard
      tone="dark"
      title={`${a.lga} · ${stateLabel}`}
      big={`${mm(a.measured_mm)} mm measured · ${mmOrDash(f)} mm forecast`}
      rows={[
        { k: 'Measured · NASA IMERG', v: `${mm(a.measured_mm)} mm average · wettest cell ${mm(a.measured_max_mm)} mm · ${Math.round(100 * a.wet_share_1mm)}% of the area 1 mm+` },
        { k: MODEL_LABEL[model], v: f === null ? 'no run stored' : `${mm(f)} mm, made ${leadLabel(lead)}` },
        { k: MODEL_LABEL[other(model)], v: g === null ? 'no run stored' : `${mm(g)} mm, made ${leadLabel(lead)}` },
        { k: `${MODEL_SHORT[model]} as the day came`, v: `${ladder} mm` },
        { k: 'Ensemble chance, 1 mm+', v: p1 === undefined ? 'chances run to 9 days before' : p1 === null ? 'not stored' : `${Math.round(p1)}% made ${leadLabel(lead)}` },
        ...(r ? [{ k: 'Season here', v: `caught ${r[0]} of ${r[0] + r[2]} rain days · ${r[0]} of ${r[0] + r[1]} rain calls confirmed` }] : []),
      ]}
      why={daySentence(a, model, lead, day)}
      onClose={onClose}
    />
  );
}

export function CheckSeasonCard({ l, model, lead, leadIdx, s, stateLabel, unit, onClose }: {
  l: CheckLga; model: CheckModel; lead: number; leadIdx: number; s: ForecastCheck; stateLabel: string; unit: string;
  onClose: () => void;
}) {
  const c = lgaCounts(l, model, leadIdx);
  const o = lgaCounts(l, other(model), leadIdx);
  if (!c) return null;
  const a = agreed(c);
  const why = a.den < 5
    ? `${l.lga} had too few rain days in the record to score (${l.wet} measured).`
    : `Since ${s.first_day ? dayMonth(s.first_day) : 'the start'}, NASA’s satellites measured rain on ${l.wet} of ${l.days} days over ${l.lga}. ` +
      `Forecasts made ${leadLabel(lead)} by the ${MODEL_SHORT[model]} had rain on ${c[0] + c[1]} days; both had rain on ${c[0]}.`;
  return (
    <HaloCard
      tone="dark"
      title={`${l.lga} · ${stateLabel}`}
      big={`${pctText(a)} of rain days agreed`}
      rows={[
        { k: 'Rain days caught', v: `${c[0]} of ${c[0] + c[2]} (${pctText(caught(c))})` },
        { k: 'Rain calls confirmed', v: `${c[0]} of ${c[0] + c[1]} (${pctText(confirmed(c))})` },
        { k: 'Rain total', v: `forecast ${mm(c[4])} mm vs ${mm(c[5])} mm measured (${signed(totalBias(c))})` },
        { k: MODEL_LABEL[other(model)], v: o ? `${pctText(agreed(o))} agreed · caught ${pctText(caught(o))} · confirmed ${pctText(confirmed(o))}` : 'not available' },
        { k: 'Days checked', v: `${l.days} · ${l.wet} with rain measured (1 mm+ over the ${unit})` },
      ]}
      why={why}
      onClose={onClose}
    />
  );
}
