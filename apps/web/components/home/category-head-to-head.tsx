'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Bucket, CategoryCompare, Side } from '@/lib/api/category-compare';
import { formatCount } from '@/lib/format';
import { isValidPrice } from '@/lib/money';
import { navHref } from '@/lib/nav';
import { errorText } from '../error-notice';
import { Card } from '../ui/card';
import { Known } from '../ui/known';
import { Money, Pct } from '../ui/money';
import { RetailerDot } from '../ui/retailer-dot';
import type { PairState } from '../widgets/use-compare';
import { bucketCheaper, gapWidth, retailerTone, share, widestGap } from './model';

type Pair = { base: string; other: string; name: (id: string) => string };

/**
 * Where each shop is cheaper, category by category, on the full catalogues: both shops' product
 * counts as paired bars, both medians, and the API's gap as a zero-centred bar with the signed
 * percentage. Plain HTML and CSS; nothing is recomputed from the medians on screen.
 */
export function CategoryHeadToHead({
  state,
  pair,
  span = 12,
}: {
  state: PairState<CategoryCompare>;
  pair: Pair;
  /** Its width on the Overview's 12-column grid: two thirds beside the basket, else the full row. */
  span?: 8 | 12;
}) {
  const t = useTranslations('widgets.categories');
  const te = useTranslations('errors');
  const locale = useLocale();
  const common = {
    id: 'w-categories',
    title: t('title'),
    question: t('question', { base: pair.name(pair.base), other: pair.name(pair.other) }),
    tools: (
      <Link href={navHref('prices', locale)} className="btn text-sm focus-visible:outline-2">
        {t('open')}
      </Link>
    ),
    flush: true,
    skeleton: 'table' as const,
    span,
  };
  if (state.kind === 'loading') return <Card {...common} state="loading" />;
  if (state.kind === 'error')
    return (
      <Card
        {...common}
        state="error"
        reason={
          <span className="flex flex-wrap items-center gap-3">
            {errorText(te, state.error)}
            <button type="button" onClick={state.retry} className="btn focus-visible:outline-2">
              {te('retry')}
            </button>
          </span>
        }
      />
    );
  if (state.kind === 'empty' || state.data.buckets.length === 0)
    return <Card {...common} state="empty" reason={t('notAvailable')} />;
  return (
    <Card {...common}>
      <Body data={state.data} pair={pair} />
    </Card>
  );
}

function Body({ data, pair }: { data: CategoryCompare; pair: Pair }) {
  const t = useTranslations('widgets.categories');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const lc = locale === 'ar' ? 'ar' : 'en';
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const label = (b: Bucket) => b.label?.[lc] || t(`name.${b.key}`);
  // The widest count and gap on the table, so every bar is read against the same scale.
  const maxN = Math.max(0, ...data.buckets.flatMap((b) => [side(b, pair.base).n, side(b, pair.other).n]));
  const maxGap = widestGap(data.buckets);
  const currency = data.buckets.map((b) => side(b, pair.base).median?.currency).find(Boolean) ?? null;

  const count = (b: Bucket, id: string, i: 0 | 1) => {
    const n = side(b, id).n;
    return (
      <span className="grid grid-cols-[1fr_auto] items-center gap-2">
        <span aria-hidden className="block h-1.5 overflow-hidden rounded-full bg-line-2">
          <i
            className="block h-full rounded-full"
            style={{ width: `${share(n, maxN)}%`, background: retailerTone(id, i) }}
          />
        </span>
        <span className="text-xs text-ink-2 tabular-nums">
          <span className="sr-only">{pair.name(id)} </span>
          {formatCount(n, locale)}
        </span>
      </span>
    );
  };

  /** A side's median, or in its place why there is none: blocked by the retailer, or too few. */
  const median = (b: Bucket, id: string) => {
    const s = side(b, id);
    if (s.status === 'ok' && s.median && isValidPrice(s.median))
      return <Money m={s.median} locale={locale} />;
    return (
      <span className="text-xs text-ink-2">
        {s.status === 'blocked' ? (
          <Known t={tr} v={s.reason ?? 'retailer_blocked'} />
        ) : (
          t('tooFew', { n: s.n })
        )}
      </span>
    );
  };

  /** The gap as the API sent it: a bar off the zero line toward the cheaper side, and the number. */
  const gap = (b: Bucket) => {
    const who = bucketCheaper(b, pair.base, pair.other);
    if (who === null)
      return (
        <span className="text-xs text-ink-2">
          {b.status === 'no_gap' && b.gapReason ? <Known t={tr} v={b.gapReason} /> : '–'}
        </span>
      );
    if (who === 'same')
      return (
        <span className="inline-flex items-center gap-2">
          <span className="gapbar" aria-hidden />
          <span className="text-xs text-ink-2">{t('same')}</span>
        </span>
      );
    // Negative means `other` is cheaper: the fill runs to the start side and reads as good for it.
    const otherCheaper = who === pair.other;
    return (
      <span className="inline-flex items-center gap-2">
        <span className="gapbar" aria-hidden>
          <i data-side={otherCheaper ? 'good' : 'bad'} style={{ width: `${gapWidth(b.gapPct!, maxGap)}%` }} />
        </span>
        <span className={`text-sm font-medium ${otherCheaper ? 'text-good' : 'text-bad'}`}>
          <Pct v={b.gapPct!} />
        </span>
      </span>
    );
  };

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th scope="col" className="th ps-5 text-start">
                {t('category')}
              </th>
              <th scope="col" className="th text-start max-sm:hidden">
                {t('products')}
              </th>
              <th scope="col" className="th text-end whitespace-nowrap">
                <RetailerDot id={pair.base} side={0} /> {t('medianOf', { shop: base })}
              </th>
              <th scope="col" className="th text-end whitespace-nowrap">
                <RetailerDot id={pair.other} side={1} /> {t('medianOf', { shop: other })}
              </th>
              <th scope="col" className="th pe-5 text-start">
                {t('gap')}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.buckets.map((b) => (
              <tr key={b.key} className="border-t border-line-2">
                <th scope="row" className="ps-5 py-2 text-start font-medium">
                  {label(b)}
                </th>
                <td className="min-w-32 py-2 pe-3 max-sm:hidden">
                  <span className="grid gap-1">
                    {count(b, pair.base, 0)}
                    {count(b, pair.other, 1)}
                  </span>
                </td>
                <td className="py-2 pe-3 text-end tabular-nums">{median(b, pair.base)}</td>
                <td className="py-2 pe-3 text-end tabular-nums">{median(b, pair.other)}</td>
                <td className="py-2 pe-5">{gap(b)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="px-5 pt-3 text-xs text-ink-2">
        {currency ? `${t('inCurrency', { currency })} ` : ''}
        {t('note', { base, other })}
        {data.minN > 0 && ` ${t('minN', { n: data.minN })}`}
        {data.unmapped.length > 0 &&
          ` ${t('unmapped', {
            n: formatCount(
              data.unmapped.reduce((a, u) => a + u.n, 0),
              locale,
            ),
          })}`}
      </p>
    </>
  );
}

/** A bucket's side for a retailer; a side the API left out is an empty, too-few one. */
function side(b: Bucket, id: string): Side {
  return (
    b.sides[id] ?? {
      n: 0,
      median: null,
      mean: null,
      p25: null,
      p75: null,
      min: null,
      max: null,
      status: 'too_few',
      reason: null,
    }
  );
}
