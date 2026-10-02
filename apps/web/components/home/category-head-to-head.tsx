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
import { RetailerDot, retailerColor } from '../ui/retailer-dot';
import type { PairState } from '../widgets/use-compare';
import { bucketCheaper, gapWidth, share, widestGap } from './model';

type Pair = { base: string; other: string; name: (id: string) => string };

/**
 * Where each shop is cheaper, category by category, on the full catalogues: both shops' product
 * counts as paired bars, both medians, and the API's gap as a zero-centred bar in the cheaper
 * shop's colour with the signed percentage and the shop named (no green or red: a lower median is
 * a fact, not a verdict). Plain HTML and CSS; nothing is recomputed from the medians on screen.
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
  const maxN = Math.max(
    0,
    ...data.buckets.flatMap((b) => [side(b, pair.base)?.n ?? 0, side(b, pair.other)?.n ?? 0]),
  );
  const maxGap = widestGap(data.buckets);
  const currency = data.buckets.map((b) => side(b, pair.base)?.median?.currency).find(Boolean) ?? null;

  /** A side's product count as a bar; a side the API left out has no count, so no bar and no 0. */
  const count = (b: Bucket, id: string, i: 0 | 1) => {
    const s = side(b, id);
    return (
      <span className="grid grid-cols-[1fr_auto] items-center gap-2">
        <span aria-hidden className="block h-1.5 overflow-hidden rounded-full bg-line-2">
          {s && (
            <i
              className="block h-full rounded-full"
              style={{ width: `${share(s.n, maxN)}%`, background: retailerColor(id, i) }}
            />
          )}
        </span>
        <span className="text-xs text-ink-2 tabular-nums">
          <span className="sr-only">{pair.name(id)} </span>
          {s ? formatCount(s.n, locale) : '–'}
        </span>
      </span>
    );
  };

  /**
   * A side's median, or in its place why there is none: blocked by the retailer, too few priced
   * products (the API's own count), or not sent for this side at all.
   */
  const median = (b: Bucket, id: string) => {
    const s = side(b, id);
    if (s?.status === 'ok' && s.median && isValidPrice(s.median))
      return <Money m={s.median} locale={locale} />;
    return (
      <span className="text-xs text-ink-2">
        {!s ? (
          t('sideMissing')
        ) : s.status === 'blocked' ? (
          <Known t={tr} v={s.reason ?? 'retailer_blocked'} />
        ) : (
          t('tooFew', { n: s.n })
        )}
      </span>
    );
  };

  /**
   * The gap as the API sent it: a bar off the zero line toward the cheaper side, in that shop's
   * colour, the signed number, and the shop named.
   */
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
    // Negative means `other` is cheaper: the fill runs to the start side, in `other`'s colour.
    const otherCheaper = who === pair.other;
    return (
      <span className="inline-flex items-center gap-2">
        <span className="gapbar" aria-hidden>
          <i
            data-shop={who}
            data-at={otherCheaper ? 'start' : 'end'}
            style={{
              width: `${gapWidth(b.gapPct!, maxGap)}%`,
              background: retailerColor(who, otherCheaper ? 1 : 0),
            }}
          />
        </span>
        <span className="text-sm font-medium tabular-nums">
          <Pct v={b.gapPct!} />
        </span>
        <span className="text-xs whitespace-nowrap text-ink-2">
          {t('cheaperAt', { shop: pair.name(who) })}
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
                <RetailerDot id={pair.base} index={0} /> {t('medianOf', { shop: base })}
              </th>
              <th scope="col" className="th text-end whitespace-nowrap">
                <RetailerDot id={pair.other} index={1} /> {t('medianOf', { shop: other })}
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
        {data.unmapped.length > 0 && ` ${t('unmapped', { n: data.unmapped.reduce((a, u) => a + u.n, 0) })}`}
      </p>
    </>
  );
}

/** A bucket's side for a retailer, or null when the API left it out: not a count of zero. */
function side(b: Bucket, id: string): Side | null {
  return b.sides[id] ?? null;
}
