'use client';

/**
 * The list beside the forecast-check map. On a day: where the forecast and the
 * satellites disagreed — rain measured but not forecast, then rain forecast
 * but not measured — each with how the forecast for that day changed as the
 * day came closer. On the season record: each LGA's own record.
 */

import type { CheckDayArea, CheckLga, CheckModel } from '@/hooks/useForecastCheck';
import {
  agreed, caught, confirmed, forecastAt, lgaCounts, MIN_RAIN_DAYS, MODEL_SHORT, outcome, pctText, totalBias, signed,
  type Outcome,
} from './checkModel';
import { dayMonth, mm } from './forecastModel';

const LIST_MAX = 40;

function Evolution({ a, model, lead }: { a: CheckDayArea; model: CheckModel; lead: number }) {
  // Oldest run on the left, the same morning on the right — the forecast for one
  // day as it came closer. The measured total is the line across.
  const xs = (model === 'ifs' ? a.ifs_mm : a.aifs_mm).slice().reverse();
  const top = Math.max(1, a.measured_mm, ...xs.map((v) => v ?? 0));
  return (
    <span className="ck-evo" aria-hidden="true">
      {xs.map((v, i) => {
        const k = xs.length - 1 - i;
        return (
          <i key={k} className={`${v === null ? 'na' : v < 1 ? 'dry' : ''}${k === lead ? ' on' : ''}`}
            style={{ height: `${v === null ? 100 : Math.max(6, (v / top) * 100)}%` }} />
        );
      })}
      <b style={{ bottom: `${Math.min(100, (a.measured_mm / top) * 100)}%` }} />
    </span>
  );
}

function DayCard({ a, kind, model, lead, selected, onSelect }: {
  a: CheckDayArea; kind: Outcome; model: CheckModel; lead: number; selected: boolean; onSelect: (lga: string) => void;
}) {
  const f = forecastAt(a, model, lead) ?? 0;
  const big = kind === 'false' ? f : a.measured_mm;
  return (
    <button type="button" className={`sgr-card ${selected ? 'is-on' : ''}`} aria-pressed={selected} onClick={() => onSelect(a.lga)}>
      <span className="sgr-card-lga">{a.lga}</span>
      <span className={`sgr-card-mm ck-mm--${kind}`}>{mm(big)}<small> mm {kind === 'false' ? 'forecast' : 'measured'}</small></span>
      <span className="sgr-card-body">
        <Evolution a={a} model={model} lead={lead} />
        <span>
          <span className="sgr-card-strong">
            {kind === 'miss' ? `Forecast ${mm(f)} mm` : kind === 'false' ? `Measured ${mm(a.measured_mm)} mm` : `Forecast ${mm(f)} mm`}
          </span>
          {` · wettest cell ${mm(a.measured_max_mm)} mm · ${Math.round(100 * a.wet_share_1mm)}% of the area wet`}
        </span>
        <span>Bars: the {MODEL_SHORT[model]}’s forecast for this day, made 14 days before (left) to the same morning (right); line = measured</span>
      </span>
    </button>
  );
}

export function CheckDayList({ areas, model, lead, day, selected, onSelect, unit }: {
  areas: CheckDayArea[]; model: CheckModel; lead: number; day: string; selected: string | null;
  onSelect: (lga: string) => void; unit: string;
}) {
  const rows = areas.map((a) => ({ a, o: outcome(forecastAt(a, model, lead), a.measured_mm) }));
  const missed = rows.filter((x) => x.o === 'miss').sort((x, y) => y.a.measured_mm - x.a.measured_mm);
  const extra = rows.filter((x) => x.o === 'false')
    .sort((x, y) => (forecastAt(y.a, model, lead) ?? 0) - (forecastAt(x.a, model, lead) ?? 0));
  const hits = rows.filter((x) => x.o === 'hit').sort((x, y) => y.a.measured_mm - x.a.measured_mm);
  const dry = rows.filter((x) => x.o === 'dry').length;
  const none = rows.filter((x) => x.o === null).length;
  const shown = [...missed.map((x) => ({ ...x, kind: 'miss' as const })), ...extra.map((x) => ({ ...x, kind: 'false' as const }))];

  return (
    <div className="sgr-listcol">
      <h3 className="sgr-h2">{shown.length ? 'Where forecast and satellites disagreed' : 'Forecast and satellites agreed'}</h3>
      <p className="fc-listnote">
        {dayMonth(day)} · {hits.length} wet {unit}s caught · {missed.length} missed · {extra.length} forecast but not measured ·{' '}
        {dry} dry, called dry{none ? ` · ${none} with no stored run` : ''}. Rain missed first, wettest first.
      </p>
      {(shown.length ? shown : hits.map((x) => ({ ...x, kind: 'hit' as const }))).slice(0, LIST_MAX).map((x) => (
        <DayCard key={x.a.lga} a={x.a} kind={x.kind} model={model} lead={lead} selected={selected === x.a.lga} onSelect={onSelect} />
      ))}
      {shown.length > LIST_MAX && <p className="fc-listnote">{shown.length - LIST_MAX} more — click them on the map.</p>}
    </div>
  );
}

export function CheckRecordList({ lgas, model, leadIdx, lead, selected, onSelect, unit }: {
  lgas: CheckLga[]; model: CheckModel; leadIdx: number; lead: number; selected: string | null;
  onSelect: (lga: string) => void; unit: string;
}) {
  const scored = lgas.filter((l) => l.wet >= MIN_RAIN_DAYS).sort((x, y) => y.wet - x.wet);
  const unscored = lgas.length - scored.length;
  return (
    <div className="sgr-listcol">
      <h3 className="sgr-h2">Season record by {unit}</h3>
      <p className="fc-listnote">
        The {MODEL_SHORT[model]}’s forecasts made {lead === 0 ? 'the same morning' : `${lead} day${lead === 1 ? '' : 's'} before`}, wettest {unit}s first
        {' '}· big number: on days either side had rain, the share where both did
        {unscored ? ` · ${unscored} with under ${MIN_RAIN_DAYS} rain days are not scored` : ''}.
      </p>
      {scored.slice(0, LIST_MAX).map((l) => {
        const c = lgaCounts(l, model, leadIdx);
        if (!c) return null;
        return (
          <button key={l.lga} type="button" className={`sgr-card ${selected === l.lga ? 'is-on' : ''}`}
            aria-pressed={selected === l.lga} onClick={() => onSelect(l.lga)}>
            <span className="sgr-card-lga">{l.lga}</span>
            <span className="sgr-card-mm ck-mm--hit">{pctText(agreed(c))}<small> agreed</small></span>
            <span className="sgr-card-body">
              <span>
                <span className="sgr-card-strong">Caught {c[0]} of {c[0] + c[2]} rain days ({pctText(caught(c))})</span>
                {` · ${c[0]} of ${c[0] + c[1]} rain calls confirmed (${pctText(confirmed(c))})`}
              </span>
              <span>Rain total: forecast {mm(c[4])} mm vs {mm(c[5])} mm measured ({signed(totalBias(c))}) · {l.days} days checked</span>
            </span>
          </button>
        );
      })}
      {scored.length > LIST_MAX && <p className="fc-listnote">{scored.length - LIST_MAX} more — click them on the map.</p>}
    </div>
  );
}
