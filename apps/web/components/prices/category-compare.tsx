'use client';

import dynamic from 'next/dynamic';
import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Bucket, CategoryCompare, Side } from '@/lib/api/category-compare';
import type { Envelope, Money } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import { formatMoney, isValidPrice } from '@/lib/money';
import { ErrorNotice } from '../error-notice';
import { Card } from '../ui/card';
import { CaveatNotes } from '../ui/env-notes';
import { Known } from '../ui/known';
import { Skeleton } from '../ui/skeleton';
import { pct } from '../widgets/model';
import type { PairState } from '../widgets/use-compare';

const BucketGapWidget = dynamic(() => import('../widgets/charts').then((m) => m.BucketGapWidget), {
  ssr: false,
  loading: () => <Skeleton kind="chart" />,
});

type Pair = { base: string; other: string; name: (id: string) => string };

/** Retailer tones in pair order (base, other), the same order the product grid and the charts use. */
const TONE = ['bg-blush text-blush-ink', 'bg-sky text-sky-ink'] as const;
const BAR = ['fill-series-a', 'fill-series-b'] as const;
const WHISKER = ['stroke-series-a', 'stroke-series-b'] as const;

/** Range-bar geometry: a small inline SVG per row, one shared scale for the whole table. */
const W = 120;
const H = 16;

/**
 * The category centrepiece: both full catalogues across the nine shared buckets, as a table (or
 * stacked cards on a phone), a diverging gap chart, and what was left out and why. The state is a
 * prop so the card renders the same from the hook and from a test.
 */
export function CategoryCompareCard({
  state,
  pair,
  locale,
}: {
  state: PairState<CategoryCompare>;
  pair: Pair;
  locale: string;
}) {
  const t = useTranslations('widgets.buckets');
  const tc = useTranslations('card');
  const meta = (env: Envelope<unknown> | null) =>
    env ? t('meta', { date: formatDate(env.meta.cutoff, locale) }) : null;
  const common = { id: 'p-buckets', title: t('title'), question: t('question'), span: 12 as const };
  if (state.kind === 'loading')
    return <Card {...common} state="loading" skeleton="table" reason={tc('loading')} />;
  if (state.kind === 'error')
    return (
      <Card {...common} state="error" reason={<ErrorNotice error={state.error} onRetry={state.retry} />} />
    );
  if (state.kind === 'empty')
    return <Card {...common} meta={meta(state.env)} state="empty" reason={t('notAvailable')} />;
  return (
    <Card {...common} meta={meta(state.env)}>
      <CaveatNotes caveats={state.env.caveats} className="mb-4" />
      <CategoryCompareBody data={state.data} pair={pair} locale={locale} />
    </Card>
  );
}

function CategoryCompareBody({ data, pair, locale }: { data: CategoryCompare; pair: Pair; locale: string }) {
  const t = useTranslations('widgets.buckets');
  const tr = useTranslations('reasons');
  const rtl = locale === 'ar';
  const lc = rtl ? 'ar' : 'en';
  const ids: [string, string] = [pair.base, pair.other];
  const label = (b: Bucket) => b.label?.[lc] || t(`name.${b.key}`);
  const scale = logScale(data.buckets, ids);
  const ok = data.buckets.filter((b) => b.status === 'ok');
  const thin = data.buckets.filter((b) => b.status === 'too_few');
  const blocked = data.buckets.filter((b) => b.status === 'blocked');

  /** What a side shows in place of its figures when it has none. */
  const sideNote = (s: Side) =>
    s.status === 'blocked' ? (
      <Known t={tr} v={s.reason ?? 'retailer_blocked'} />
    ) : (
      t('tooFew', { n: formatCount(s.n, locale) })
    );

  /** The cheaper chip, or a muted dash when the row has no gap. */
  const chip = (b: Bucket) => {
    if (b.status !== 'ok' || b.gapPct === null) return <span className="text-ink-2">–</span>;
    // The API decides when two medians are the same; its verdict is not second-guessed here.
    if (b.cheaper === 'same') return <span className="pill bg-surface-2 text-ink-2">{t('same')}</span>;
    const who = b.cheaper ?? (Number(b.gapPct) > 0 ? pair.base : pair.other);
    const tone = TONE[ids.indexOf(who)] ?? TONE[0];
    return (
      <span className={`pill ${tone}`}>
        {t('cheaperBy', { name: pair.name(who), pct: pct(String(Math.abs(Number(b.gapPct))), locale) })}
      </span>
    );
  };

  const price = (m: Money) => (isValidPrice(m) ? formatMoney(m, lc) : null);

  /** Median in bold with the mean beneath; nothing for a null mean (never 0). */
  const figures = (s: Side) => (
    <>
      <b className="font-semibold text-ink">{s.median && price(s.median)}</b>
      {s.mean && price(s.mean) && (
        <span className="block text-xs text-ink-2">
          {t('mean')} {price(s.mean)}
        </span>
      )}
    </>
  );

  return (
    <div className="space-y-5">
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full text-sm">
          <colgroup>
            <col />
            <col span={3} />
            <col span={3} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th scope="col" rowSpan={2} className="th text-start">
                {t('category')}
              </th>
              {ids.map((id, i) => (
                <th key={id} scope="colgroup" colSpan={3} className="th text-start">
                  <span className={`pill ${TONE[i]}`}>{pair.name(id)}</span>
                </th>
              ))}
              <th scope="col" rowSpan={2} className="th text-start">
                {t('cheaper')}
              </th>
            </tr>
            <tr>
              {ids.map((id) => (
                <SideHead key={id} scale={scale} rtl={rtl} locale={locale} currency={scale.currency} />
              ))}
            </tr>
          </thead>
          <tbody>
            {data.buckets.map((b) => (
              <tr key={b.key} className="border-t border-line-2 align-top">
                <th scope="row" className="py-2 pe-3 text-start font-medium">
                  {label(b)}
                </th>
                {ids.map((id, i) => {
                  const s = b.sides[id]!;
                  // No figures: one cell across n, median and range, saying why (its n is in the note).
                  if (s.status !== 'ok')
                    return (
                      <td key={id} colSpan={3} className="py-2 pe-3 text-ink-2">
                        {sideNote(s)}
                      </td>
                    );
                  return (
                    <SideCells key={id} n={s.n} locale={locale}>
                      <td className="py-2 pe-3 tabular-nums">{figures(s)}</td>
                      <td className="py-2 pe-3">
                        <RangeBar side={s} scale={scale} rtl={rtl} tone={i} />
                      </td>
                    </SideCells>
                  );
                })}
                <td className="py-2 text-start">{chip(b)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink-2">{t('rangeHint')}</p>
      </div>

      <ul className="space-y-3 sm:hidden">
        {data.buckets.map((b) => (
          <li key={b.key} className="rounded-ctl border border-line-2 p-3">
            <div className="flex items-start justify-between gap-3">
              <h3 className="font-semibold">{label(b)}</h3>
              {chip(b)}
            </div>
            <dl className="mt-2 space-y-2">
              {ids.map((id, i) => {
                const s = b.sides[id]!;
                return (
                  <div key={id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                    <dt className={`pill ${TONE[i]}`}>{pair.name(id)}</dt>
                    <dd className="text-xs text-ink-2 tabular-nums">
                      {s.status === 'ok' ? `${t('n')} = ${formatCount(s.n, locale)}` : null}
                    </dd>
                    <dd className="min-w-0 flex-1 tabular-nums">
                      {s.status === 'ok' ? figures(s) : <span className="text-ink-2">{sideNote(s)}</span>}
                    </dd>
                    {s.status === 'ok' && (
                      <dd className="basis-full">
                        <RangeBar side={s} scale={scale} rtl={rtl} tone={i} />
                      </dd>
                    )}
                  </div>
                );
              })}
            </dl>
          </li>
        ))}
      </ul>

      {ok.length > 0 && (
        <BucketGapWidget data={ok} currency={scale.currency} locale={locale} pair={pair} label={label} />
      )}
      {thin.length > 0 && (
        <p className="text-sm text-ink-2">
          {t('tooFewList', {
            list: thin
              .map((b) =>
                t('tooFewItem', {
                  label: label(b),
                  sides: ids
                    .filter((id) => b.sides[id]!.status !== 'ok')
                    .map((id) => `${pair.name(id)} ${t('n')} = ${formatCount(b.sides[id]!.n, locale)}`)
                    .join(', '),
                }),
              )
              .join('; '),
          })}
        </p>
      )}
      {blocked.length > 0 && (
        <p className="text-sm text-ink-2">
          {t('withheldList', {
            list: blocked
              .map((b) =>
                t('withheldItem', {
                  label: label(b),
                  name: ids
                    .filter((id) => b.sides[id]!.status === 'blocked')
                    .map((id) => pair.name(id))
                    .join(', '),
                }),
              )
              .join('; '),
          })}{' '}
          <Known t={tr} v="retailer_blocked" />
        </p>
      )}

      <div className="space-y-1 text-xs text-ink-2">
        {ids.map(
          (id) =>
            data.otherShare[id] !== undefined && (
              <p key={id}>
                {t('otherShare', { share: pct(data.otherShare[id], locale), name: pair.name(id) })}
              </p>
            ),
        )}
        {data.unmapped.length > 0 && (
          <details>
            <summary className="cursor-pointer">
              {t('unmapped', { n: formatCount(data.unmappedPaths, locale) })}
            </summary>
            <ul className="mt-1 space-y-0.5 ps-4">
              {data.unmapped.map((u, i) => (
                <li key={`${u.retailer}:${u.category}:${i}`}>
                  {pair.name(u.retailer)} ·{' '}
                  <span lang="en" dir="ltr">
                    {u.category}
                  </span>{' '}
                  · {t('n')} = {formatCount(u.n, locale)}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}

/** The n cell then the side's figures. */
function SideCells({ n, locale, children }: { n: number; locale: string; children: ReactNode }) {
  return (
    <>
      <td className="py-2 pe-3 text-ink-2 tabular-nums">{formatCount(n, locale)}</td>
      {children}
    </>
  );
}

/** The per-retailer sub-headers: n, median, and the range column with the shared axis drawn once. */
function SideHead({
  scale,
  rtl,
  locale,
  currency,
}: {
  scale: LogScale;
  rtl: boolean;
  locale: string;
  currency: string;
}) {
  const t = useTranslations('widgets.buckets');
  return (
    <>
      <th scope="col" className="th text-start">
        {t('n')}
      </th>
      <th scope="col" className="th text-start">
        {t('median')}
      </th>
      <th scope="col" className="th text-start">
        <span className="block">{t('range')}</span>
        {scale.ticks.length > 0 && (
          <svg
            aria-hidden="true"
            viewBox={`0 0 ${W} 12`}
            width={W}
            height={12}
            className="mt-0.5 block overflow-visible"
          >
            {scale.ticks.map((v) => (
              <text
                key={v}
                x={scale.x(v, rtl)}
                y={10}
                textAnchor="middle"
                className="fill-ink-2"
                style={{ fontSize: 9, fontVariantNumeric: 'tabular-nums' }}
              >
                {whole(v, currency, locale)}
              </text>
            ))}
          </svg>
        )}
      </th>
    </>
  );
}

/** p25–p75 band with the median tick and a faint min–max whisker, on the table's shared log scale. */
function RangeBar({ side, scale, rtl, tone }: { side: Side; scale: LogScale; rtl: boolean; tone: number }) {
  const v = (m: Money | null) => (m && isValidPrice(m) ? Number(m.amount) : null);
  const med = v(side.median);
  if (med === null || !scale.ok) return null;
  const p25 = v(side.p25) ?? med;
  const p75 = v(side.p75) ?? med;
  const lo = v(side.min) ?? p25;
  const hi = v(side.max) ?? p75;
  const x0 = Math.min(scale.x(p25, rtl), scale.x(p75, rtl));
  const x1 = Math.max(scale.x(p25, rtl), scale.x(p75, rtl));
  const w0 = Math.min(scale.x(lo, rtl), scale.x(hi, rtl));
  const w1 = Math.max(scale.x(lo, rtl), scale.x(hi, rtl));
  const xm = scale.x(med, rtl);
  return (
    <svg aria-hidden="true" viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block">
      <line x1={w0} x2={w1} y1={H / 2} y2={H / 2} strokeWidth={1} className={`${WHISKER[tone]} opacity-40`} />
      <rect
        x={x0}
        y={3}
        width={Math.max(2, x1 - x0)}
        height={H - 6}
        rx={2}
        className={`${BAR[tone]} opacity-70`}
      />
      <rect x={xm - 1} y={1} width={2} height={H - 2} rx={1} className="fill-ink" />
    </svg>
  );
}

interface LogScale {
  ok: boolean;
  currency: string;
  ticks: number[];
  x: (v: number, rtl: boolean) => number;
}

/** One log scale across every ok side's min–max, with decade ticks inside it; mirrored in Arabic. */
function logScale(buckets: readonly Bucket[], ids: readonly string[]): LogScale {
  const vals: number[] = [];
  let currency = '';
  for (const b of buckets)
    for (const id of ids) {
      const s = b.sides[id];
      if (!s || s.status !== 'ok') continue;
      for (const m of [s.min, s.p25, s.median, s.p75, s.max])
        if (m && isValidPrice(m) && Number(m.amount) > 0) {
          vals.push(Number(m.amount));
          currency ||= m.currency;
        }
    }
  if (vals.length === 0) return { ok: false, currency, ticks: [], x: () => 0 };
  const lo = Math.log10(Math.min(...vals));
  const hi = Math.log10(Math.max(...vals));
  const span = hi - lo || 1;
  const pad = 4;
  const x = (v: number, rtl: boolean) => {
    const f = (Math.log10(Math.max(v, 1e-9)) - lo) / span;
    const px = pad + Math.min(1, Math.max(0, f)) * (W - 2 * pad);
    return Math.round((rtl ? W - px : px) * 10) / 10;
  };
  const ticks: number[] = [];
  for (let e = Math.ceil(lo); e <= Math.floor(hi); e++) ticks.push(10 ** e);
  return { ok: true, currency, ticks, x };
}

/** A whole-unit price for the axis, in Latin digits. */
function whole(v: number, currency: string, locale: string) {
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-AE' : 'en-AE', {
    style: 'currency',
    currency: currency || 'AED',
    numberingSystem: 'latn',
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  }).format(v);
}
