'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { Money as MoneyValue, Schemas } from '@/lib/api/types';
import { formatDate } from '@/lib/format';
import { formatMoney, isValidMoney } from '@/lib/money';
import { Known } from '../ui/known';
import { Money } from '../ui/money';

type Series = Schemas['History']['series'];

/** Line styles that stay apart in greyscale too: colour plus dash. */
const STYLES = [
  { stroke: 'var(--color-accent)', dash: '' },
  { stroke: 'var(--color-ink)', dash: '5 4' },
  { stroke: 'var(--color-warn)', dash: '2 3' },
  { stroke: 'var(--color-ink-2)', dash: '8 3 2 3' },
];

/** Plot area in viewBox units; it is stretched to the box, so lines keep a fixed pixel width. */
const W = 1000;
const H = 100;
const INSET = 6;

/**
 * Daily price per retailer. The plot is decoration for sighted users; the table under it holds
 * the same values (as the API sent them) for everyone. A day without a price is a gap in the
 * line, never interpolated.
 */
export function HistoryChart({ series, name }: { series: Series; name: (id: string) => string }) {
  const t = useTranslations('product');
  const locale = useLocale();
  const retailers = Object.keys(series);
  const dates = [...new Set(retailers.flatMap((r) => (series[r] ?? []).map((p) => p.date)))].sort();
  const priced = retailers.flatMap((r) =>
    (series[r] ?? []).flatMap((p) => (p.price && isValidMoney(p.price) ? [p.price] : [])),
  );
  if (dates.length === 0 || priced.length === 0) return <p className="text-ink-2">{t('historyEmpty')}</p>;
  // No line from a single day (owner rule): until nightly collection gives a second day, the
  // prices the API has are shown as they are, beside the reason there is no chart.
  if (dates.length < 2)
    return (
      <div>
        <p className="text-sm text-ink-2">{t('historyBegins')}</p>
        <HistoryTable series={series} dates={dates} name={name} />
      </div>
    );

  const value = (m: MoneyValue) => Number(m.amount);
  const lo = priced.reduce((a, b) => (value(b) < value(a) ? b : a));
  const hi = priced.reduce((a, b) => (value(b) > value(a) ? b : a));
  const span = value(hi) - value(lo) || Math.max(value(hi), 1);
  const x = (d: string) =>
    dates.length === 1 ? W / 2 : INSET + (dates.indexOf(d) / (dates.length - 1)) * (W - 2 * INSET);
  const y = (m: MoneyValue) => INSET + (1 - (value(m) - value(lo)) / span) * (H - 2 * INSET);

  /** Polyline segments, broken wherever a day has no price. */
  const segments = (r: string) => {
    const out: string[][] = [[]];
    for (const p of series[r] ?? []) {
      if (p.price && isValidMoney(p.price)) out[out.length - 1]!.push(`${x(p.date)},${y(p.price)}`);
      else if (out[out.length - 1]!.length) out.push([]);
    }
    return out.filter((s) => s.length);
  };
  const lc = locale === 'ar' ? 'ar' : 'en';
  // The plot runs left to right; each label still reads in the page's own direction.
  const dir = lc === 'ar' ? 'rtl' : 'ltr';
  const tick = (pt: string) => {
    const [px, py] = pt.split(',').map(Number) as [number, number];
    return `${px - 4},${py} ${px + 4},${py}`;
  };

  return (
    <figure>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {retailers.map((r, i) => {
          const s = STYLES[i % STYLES.length]!;
          return (
            <li key={r} className="flex items-center gap-2">
              <svg width="24" height="8" aria-hidden>
                <line
                  x1="0"
                  y1="4"
                  x2="24"
                  y2="4"
                  stroke={s.stroke}
                  strokeWidth="2"
                  strokeDasharray={s.dash}
                />
              </svg>
              {name(r)}
            </li>
          );
        })}
      </ul>
      {/* Time runs left to right in both languages, as in the retailers' own charts. Labels are
          HTML, so they stay readable at any width. */}
      <div dir="ltr" className="panel p-4 text-xs text-ink-2">
        <div className="flex justify-between tabular-nums">
          <bdi dir={dir}>{formatMoney(hi, lc)}</bdi>
        </div>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className="my-1 block h-40 w-full"
          role="img"
          aria-label={t('chartLabel', { retailers: retailers.map(name).join(', ') })}
        >
          {[INSET, H - INSET].map((gy) => (
            <line
              key={gy}
              x1="0"
              x2={W}
              y1={gy}
              y2={gy}
              stroke="var(--color-line)"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {retailers.map((r, i) => {
            const s = STYLES[i % STYLES.length]!;
            return (
              <g key={r}>
                {segments(r).map((pts, j) => (
                  <polyline
                    key={j}
                    // A lone priced day still shows: a short tick instead of an invisible point.
                    points={pts.length === 1 ? tick(pts[0]!) : pts.join(' ')}
                    fill="none"
                    stroke={s.stroke}
                    strokeWidth="2"
                    strokeDasharray={s.dash}
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
              </g>
            );
          })}
        </svg>
        <div className="flex justify-between tabular-nums">
          <bdi dir={dir}>{value(hi) !== value(lo) ? formatMoney(lo, lc) : ''}</bdi>
        </div>
        <div className="mt-1 flex justify-between border-t border-line pt-1">
          <bdi dir={dir}>{formatDate(dates[0]!, locale)}</bdi>
          {dates.length > 1 && <bdi dir={dir}>{formatDate(dates[dates.length - 1]!, locale)}</bdi>}
        </div>
      </div>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-accent focus-visible:outline-2">{t('historyTable')}</summary>
        <HistoryTable series={series} dates={dates} name={name} />
      </details>
    </figure>
  );
}

function HistoryTable({
  series,
  dates,
  name,
}: {
  series: Series;
  dates: string[];
  name: (id: string) => string;
}) {
  const t = useTranslations('product');
  const ta = useTranslations('availability');
  const locale = useLocale();
  const retailers = Object.keys(series);
  return (
    <div className="relative mt-2 overflow-x-auto">
      <table className="text-sm">
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="px-3 py-1.5 text-start font-medium text-ink-2">
              {t('date')}
            </th>
            {retailers.map((r) => (
              <th key={r} scope="col" className="px-3 py-1.5 text-start font-medium text-ink-2">
                {name(r)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dates.map((d) => (
            <tr key={d} className="border-t border-line">
              <th scope="row" className="px-3 py-1.5 text-start font-normal whitespace-nowrap">
                <time dateTime={d}>{formatDate(d, locale)}</time>
              </th>
              {retailers.map((r) => {
                const p = (series[r] ?? []).find((x) => x.date === d);
                return (
                  <td key={r} className="px-3 py-1.5">
                    {p?.price ? <Money m={p.price} locale={locale} /> : <span className="text-ink-2">–</span>}
                    {p?.availability && (
                      <span className="ms-2 text-xs text-ink-2">
                        <Known t={ta} v={p.availability} />
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
