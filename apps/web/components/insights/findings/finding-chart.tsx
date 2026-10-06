'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { CSSProperties, ReactNode } from 'react';
import {
  barWidth,
  cellShade,
  scale,
  signed,
  stripAxis,
  stripPos,
  type ChartRow,
  type Finding,
  type Namers,
} from '@/lib/findings';
import { formatCount } from '@/lib/format';
import { retailerColor, RetailerDot } from '../../ui/retailer-dot';
import { known } from './known';

/** Findings whose bar is a share of a total: drawn as the part filled inside its total. */
const OUT_OF = new Set<Finding['key']>(['stock']);

/** Price-band greys, cheapest lightest (design, 6 Oct): bands are an order, not shops. */
const BANDS = ['#e8eaef', '#cfd3dc', '#aeb4c2', '#7f879a', '#4b5160', '#15171f'];

/** A label wider than this many characters gets the wide label column. */
const WIDE = 24;

type Props = { finding: Finding; names: Namers; caption: string };

/**
 * The finding's one hero chart, in HTML and CSS (no chart library), from the API's chart rows:
 * bars (a filled share inside its total for counts out of a total), diverging bars around zero,
 * stacked bars, strips of dots with the median, or a matrix. Shops keep their fixed colours
 * (`retailerColor`); the numbers are the rows' own, never rescaled into new figures.
 */
export function FindingChart({ finding: f, names, caption }: Props) {
  const chart = f.chart!;
  const body =
    chart.kind === 'diverging' ? (
      <Diverging rows={chart.rows} names={names} />
    ) : chart.kind === 'stacked' ? (
      <Stacked rows={chart.rows} columns={chart.columns} unit={chart.unit} names={names} />
    ) : chart.kind === 'strips' ? (
      <Strips rows={chart.rows} names={names} />
    ) : chart.kind === 'matrix' ? (
      <Matrix rows={chart.rows} columns={chart.columns} names={names} />
    ) : (
      <Bars rows={chart.rows} unit={chart.unit} names={names} outOf={OUT_OF.has(f.key)} />
    );
  return (
    <figure className="m-0 min-w-0" data-chart={chart.kind}>
      {body}
      <figcaption className="mt-2 text-xs text-ink-2">{caption}</figcaption>
    </figure>
  );
}

function useLabel(names: Namers) {
  const t = useTranslations('insights.findings');
  return (r: ChartRow): string =>
    r.code ? (r.retailer === r.label ? names.shop(r.label) : known(t, 'codes', r.label)) : r.label;
}

function Label({ text, dot }: { text: string; dot?: string | null }) {
  return (
    <span className="truncate text-end leading-5 text-ink" title={text} dir="auto">
      {dot && (
        <span className="me-1.5 inline-block align-[-1px]">
          <RetailerDot id={dot} />
        </span>
      )}
      {text}
    </span>
  );
}

const grid = (wide: boolean, cols: string): CSSProperties => ({
  gridTemplateColumns: `${wide ? 'minmax(0,clamp(130px,30%,260px))' : 'minmax(0,clamp(96px,22%,150px))'} ${cols}`,
});

const val = 'whitespace-nowrap text-[12.5px] leading-5 text-ink-2 tabular-nums';

function Bars({
  rows,
  unit,
  names,
  outOf,
}: {
  rows: readonly ChartRow[];
  unit: string;
  names: Namers;
  outOf: boolean;
}) {
  const locale = useLocale();
  const label = useLabel(names);
  const max = outOf ? Math.max(1, ...rows.map((r) => r.of ?? 0)) : scale(rows);
  const wide = rows.some((r) => label(r).length > WIDE);
  const text = (r: ChartRow) => {
    const v = unit === 'pct' ? `${signed(r.value)}%` : formatCount(Number(r.value), locale);
    if (outOf && r.of != null) return `${v} / ${formatCount(r.of, locale)}`;
    return v;
  };
  return (
    <div
      className="grid items-center gap-x-2.5 gap-y-1.5 text-[13px]"
      style={grid(wide, 'minmax(0,1fr) auto')}
    >
      {rows.map((r, i) => (
        <Row key={i}>
          <Label text={label(r)} />
          <span className="min-w-0">
            {outOf && r.of != null ? (
              <span
                className="relative block h-3.5 rounded-xs bg-line-2"
                style={{ width: `${barWidth(String(r.of), max)}%` }}
              >
                <span
                  className="absolute inset-y-0 start-0 rounded-xs"
                  style={{ width: `${barWidth(r.value, r.of)}%`, background: color(r) }}
                />
              </span>
            ) : (
              <span
                className="block h-3.5 rounded-xs"
                style={{ width: `${barWidth(r.value, max)}%`, background: color(r) }}
              />
            )}
          </span>
          <bdi className={val}>{text(r)}</bdi>
        </Row>
      ))}
    </div>
  );
}

const color = (r: ChartRow, i = 0) => (r.retailer ? retailerColor(r.retailer, i) : 'var(--color-ink-2)');

function Row({ children }: { children: ReactNode }) {
  return <div className="contents">{children}</div>;
}

/** Bars from zero: below zero (the focus shop cheaper) toward the labels, above it away. */
function Diverging({ rows, names }: { rows: readonly ChartRow[]; names: Namers }) {
  const locale = useLocale();
  const label = useLabel(names);
  const max = scale(rows);
  const lo = Math.min(0, ...rows.map((r) => Number(r.value)));
  const hi = Math.max(0, ...rows.map((r) => Number(r.value)));
  const zero = hi === lo ? 100 : (Math.abs(lo) / (hi - lo)) * 100;
  const span = hi - lo || max;
  const top = Math.max(...rows.map((r) => Math.abs(Number(r.value))));
  return (
    <div
      className="grid items-center gap-x-2.5 gap-y-1.5 text-[13px]"
      style={grid(false, 'auto minmax(0,1fr)')}
    >
      {rows.map((r, i) => {
        const v = Number(r.value);
        const w = v === 0 ? 0.6 : (Math.abs(v) / span) * 100;
        const strong = Math.abs(v) === top && v !== 0;
        return (
          <Row key={i}>
            <span className={strong ? 'font-semibold' : ''}>
              <Label text={label(r)} />
            </span>
            <bdi className={`${val} text-end ${strong ? 'font-semibold text-ink' : ''}`}>
              {`${signed(r.value, true)}%`}
              {r.n != null && ` · n=${formatCount(r.n, locale)}`}
            </bdi>
            <span className="relative block h-4">
              <span className="absolute inset-y-0 w-px bg-ink" style={{ insetInlineStart: `${zero}%` }} />
              <span
                className="absolute top-px h-3.5 rounded-xs"
                style={{
                  width: `${w}%`,
                  insetInlineStart: v < 0 ? `${zero - w}%` : `${zero}%`,
                  background: 'var(--color-ink-2)',
                }}
              />
            </span>
          </Row>
        );
      })}
    </div>
  );
}

/** Rows under a group heading when consecutive rows share a label and differ by shop. */
function grouped(rows: readonly ChartRow[]): { label: ChartRow; rows: ChartRow[] }[] {
  const out: { label: ChartRow; rows: ChartRow[] }[] = [];
  for (const r of rows) {
    const last = out.at(-1);
    if (last && last.label.label === r.label && r.retailer) last.rows.push(r);
    else out.push({ label: r, rows: [r] });
  }
  return out;
}

function Stacked({
  rows,
  columns,
  unit,
  names,
}: {
  rows: readonly ChartRow[];
  columns: readonly string[];
  unit: string;
  names: Namers;
}) {
  const t = useTranslations('insights.findings');
  const locale = useLocale();
  const label = useLabel(names);
  const bands = columns.length > 2;
  const max = unit === 'pct' ? 100 : scale(rows);
  const fill = (r: ChartRow, j: number) =>
    bands ? BANDS[j % BANDS.length]! : j === 0 ? color(r) : `color-mix(in srgb, ${color(r)} 30%, white)`;
  const swatch = (j: number) =>
    bands ? BANDS[j % BANDS.length]! : j === 0 ? 'var(--color-ink-2)' : 'var(--color-line-3)';
  return (
    <>
      <div
        className="grid items-center gap-x-2.5 gap-y-1.5 text-[13px]"
        style={grid(false, 'minmax(0,1fr) auto')}
      >
        {grouped(rows).map((g, gi) => (
          <Row key={gi}>
            <span
              className={`col-span-full text-xs leading-4 font-semibold text-ink-2 ${gi > 0 ? 'mt-1.5' : ''}`}
              dir="auto"
            >
              {label(g.label)}
            </span>
            {g.rows.map((r, i) => (
              <Row key={i}>
                <Label text={r.retailer ? names.shop(r.retailer) : label(r)} dot={r.retailer} />
                <span
                  className="flex h-3.5 overflow-hidden rounded-xs"
                  style={{ width: `${barWidth(r.value, max)}%` }}
                >
                  {r.parts.map((p, j) => (
                    <span
                      key={j}
                      className="block h-full"
                      title={known(t, 'codes', columns[j] ?? '')}
                      style={{
                        width: `${Number(r.value) > 0 ? (Number(p) / Number(r.value)) * 100 : 0}%`,
                        background: fill(r, j),
                      }}
                    />
                  ))}
                </span>
                <bdi className={val}>
                  {unit === 'pct' && r.n != null
                    ? `n=${formatCount(r.n, locale)}`
                    : r.parts.map((p) => formatCount(Number(p), locale)).join(' + ')}
                </bdi>
              </Row>
            ))}
          </Row>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-ink-2">
        {columns.map((c, j) => (
          <span key={c}>
            <i
              className="me-1 inline-block size-2.5 rounded-xs align-[-1px]"
              style={{ background: swatch(j) }}
            />
            <bdi>{known(t, 'codes', c)}</bdi>
          </span>
        ))}
      </div>
    </>
  );
}

/** One strip per row: every value a dot, those below zero (inverted) solid, the median a tick. */
function Strips({ rows, names }: { rows: readonly ChartRow[]; names: Namers }) {
  const label = useLabel(names);
  const axis = stripAxis(rows);
  return (
    <div dir="ltr">
      <div className="grid items-center gap-x-2.5 gap-y-1.5 text-[13px]" style={grid(false, 'minmax(0,1fr)')}>
        {grouped(rows).map((g, gi) => (
          <Row key={gi}>
            <span
              className={`col-span-full text-xs leading-4 font-semibold text-ink-2 ${gi > 0 ? 'mt-1.5' : ''}`}
              dir="auto"
            >
              {label(g.label)}
            </span>
            {g.rows.map((r, i) => (
              <Row key={i}>
                <Label text={r.retailer ? names.shop(r.retailer) : label(r)} dot={r.retailer} />
                <span className="relative block h-[22px] rounded-[3px] bg-surface-2">
                  {r.parts.map((p, j) => {
                    const inv = Number(p) < 0;
                    return (
                      <i
                        key={j}
                        className={`absolute top-1/2 rounded-full ${inv ? '-ms-[4.5px] -mt-[4.5px] size-[9px]' : '-ms-[3.5px] -mt-[3.5px] size-[7px] opacity-40'}`}
                        style={{ left: `${stripPos(Number(p), axis)}%`, background: color(r) }}
                      />
                    );
                  })}
                  <b
                    className="absolute inset-y-0 -ms-px w-0 border-l border-dashed border-bad"
                    style={{ left: `${stripPos(0, axis)}%` }}
                  />
                  <b
                    className="absolute inset-y-0 -ms-px w-0.5 bg-ink"
                    style={{ left: `${stripPos(Number(r.value), axis)}%` }}
                    title={`${signed(r.value, true)}%`}
                  />
                </span>
              </Row>
            ))}
          </Row>
        ))}
      </div>
      <div
        className="mt-1 flex justify-between text-[11px] text-ink-2 tabular-nums"
        style={{ marginInlineStart: 'calc(clamp(96px,22%,150px) + 10px)' }}
      >
        <span>{`${signed(String(Math.round(axis.min)), true)}%`}</span>
        <span>0</span>
        <span>{`${signed(String(Math.round(axis.max)), true)}%`}</span>
      </div>
    </div>
  );
}

function Matrix({
  rows,
  columns,
  names,
}: {
  rows: readonly ChartRow[];
  columns: readonly string[];
  names: Namers;
}) {
  const t = useTranslations('insights.findings');
  const locale = useLocale();
  const label = useLabel(names);
  return (
    <div
      className="grid items-center gap-1 text-[13px]"
      style={{ gridTemplateColumns: `auto repeat(${columns.length}, minmax(0,1fr))` }}
    >
      {rows.map((r, i) => (
        <Row key={i}>
          <span className="pe-1.5">
            <Label text={label(r)} />
          </span>
          {r.parts.map((p, j) => {
            const shade = cellShade(p, rows);
            return (
              <span
                key={j}
                className={`flex h-[30px] items-center justify-center rounded-[3px] font-semibold tabular-nums ${shade > 0.55 ? 'text-white' : 'text-ink'}`}
                style={{ background: `color-mix(in srgb, ${color(r)} ${Math.round(shade * 100)}%, white)` }}
              >
                {formatCount(Number(p), locale)}
              </span>
            );
          })}
        </Row>
      ))}
      <span />
      {columns.map((c) => (
        <span key={c} className="text-center text-[11.5px] text-ink-2">
          {known(t, 'codes', c)}
        </span>
      ))}
    </div>
  );
}
