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
import { Tip } from '../ui/tip';
import type { PairState } from '../widgets/use-compare';
import { bucketCheaper, categoryRead, gapWidth, widestGap } from './model';

type Pair = { base: string; other: string; name: (id: string) => string };

/**
 * Where each shop is cheaper, category by category, on the full catalogues. The title is the
 * finding (who is cheaper in how many of the compared categories, by the API's own `cheaper`);
 * the rows rank by the size of the gap, widest first, each with both medians, both product
 * counts and the API's gap as a zero-centred bar in the cheaper shop's colour (no green or red:
 * a lower median is a fact, not a verdict). Method notes sit behind the info tip, not in prose.
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
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const data = state.kind === 'ready' ? state.data : null;
  const read = data ? categoryRead(data.buckets, pair.base, pair.other) : null;
  const title =
    !read || read.compared === 0
      ? t('title')
      : read.same === read.compared
        ? t('allSame', { n: read.compared, base, other })
        : read.base === read.other
          ? t('tie', { k: read.base, n: read.compared, base, other })
          : t('lead', {
              shop: read.base > read.other ? base : other,
              k: Math.max(read.base, read.other),
              n: read.compared,
            });
  const currency = data?.buckets.map((b) => side(b, pair.base)?.median?.currency).find(Boolean) ?? null;
  const unmapped = data?.unmapped.reduce((a, u) => a + u.n, 0) ?? 0;
  const common = {
    id: 'w-categories',
    title,
    meta:
      read && read.compared > 0 ? <span className="font-normal text-ink-3">{t('title')}</span> : undefined,
    tools: (
      <>
        {data && (
          <Tip
            at="end"
            text={[
              t('note', { base, other }),
              data.minN > 0 ? t('minN', { n: data.minN }) : '',
              unmapped > 0 ? t('unmapped', { n: unmapped }) : '',
              currency ? t('inCurrency', { currency }) : '',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            <span className="pill bg-surface-2 text-ink-2" data-info>
              {t('about')}
            </span>
          </Tip>
        )}
        <Link href={navHref('prices', locale)} className="btn text-sm focus-visible:outline-2">
          {t('open')}
        </Link>
      </>
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
  if (!data || data.buckets.length === 0)
    return <Card {...common} state="empty" reason={t('notAvailable')} />;
  return (
    <Card {...common}>
      <Body data={data} pair={pair} />
    </Card>
  );
}

/** Rows with a gap first, widest first; then the rest in the API's order (too few, no gap, blocked). */
export function rankBuckets(buckets: readonly Bucket[]): Bucket[] {
  const gap = (b: Bucket) => (b.status === 'ok' && b.gapPct !== null ? Math.abs(Number(b.gapPct)) : -1);
  return buckets
    .map((b, i) => ({ b, i, g: gap(b) }))
    .sort((x, y) => (y.g === x.g ? x.i - y.i : y.g - x.g))
    .map((x) => x.b);
}

function Body({ data, pair }: { data: CategoryCompare; pair: Pair }) {
  const t = useTranslations('widgets.categories');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const lc = locale === 'ar' ? 'ar' : 'en';
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const label = (b: Bucket) => b.label?.[lc] || t(`name.${b.key}`);
  // The widest gap on the table, so every bar is read against the same scale.
  const maxGap = widestGap(data.buckets);

  /**
   * A side's median with its product count under it, or in the median's place why there is none:
   * blocked by the retailer, too few priced products (the API's own count), or not sent at all.
   */
  const median = (b: Bucket, id: string) => {
    const s = side(b, id);
    return (
      <span className="grid justify-items-end gap-0.5">
        {s?.status === 'ok' && s.median && isValidPrice(s.median) ? (
          <Money m={s.median} locale={locale} />
        ) : (
          <span className="text-xs text-ink-2">
            {!s ? (
              t('sideMissing')
            ) : s.status === 'blocked' ? (
              <Known t={tr} v={s.reason ?? 'retailer_blocked'} />
            ) : (
              t('tooFew', { n: s.n })
            )}
          </span>
        )}
        {s && (
          <span className="text-[11px] text-ink-3 tabular-nums">
            <span className="sr-only">{pair.name(id)} </span>
            {t('n', { n: formatCount(s.n, locale) })}
          </span>
        )}
      </span>
    );
  };

  /**
   * The gap as the API sent it: a bar off the zero line toward the cheaper side, in that shop's
   * colour, and a chip with the shop's dot and the signed number.
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
          <span className="pill bg-surface-2 text-ink-2">{t('same')}</span>
        </span>
      );
    // Negative means `other` is cheaper: the fill runs to the start side, in `other`'s colour.
    const otherCheaper = who === pair.other;
    return (
      <span className="inline-flex items-center gap-2">
        <span className="gapbar" aria-hidden>
          <i
            className="grow"
            data-shop={who}
            data-at={otherCheaper ? 'start' : 'end'}
            style={{
              width: `${gapWidth(b.gapPct!, maxGap)}%`,
              background: retailerColor(who, otherCheaper ? 1 : 0),
              transformOrigin: otherCheaper ? '100% 50%' : '0 50%',
            }}
          />
        </span>
        <span className="pill gap-1.5 bg-surface-2 text-sm font-medium tabular-nums">
          <RetailerDot id={who} index={otherCheaper ? 1 : 0} />
          <Pct v={b.gapPct!} />
          <span className="sr-only">{t('cheaperAt', { shop: pair.name(who) })}</span>
        </span>
      </span>
    );
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>
            <th scope="col" className="th ps-5 text-start">
              {t('category')}
            </th>
            <th scope="col" className="th text-end whitespace-nowrap">
              <RetailerDot id={pair.base} index={0} /> {base}
            </th>
            <th scope="col" className="th text-end whitespace-nowrap">
              <RetailerDot id={pair.other} index={1} /> {other}
            </th>
            <th scope="col" className="th pe-5 text-start">
              {t('gap')}
            </th>
          </tr>
        </thead>
        <tbody>
          {rankBuckets(data.buckets).map((b) => (
            <tr key={b.key} className="border-t border-line-2">
              <th scope="row" className="ps-5 py-2 text-start font-medium">
                {label(b)}
              </th>
              <td className="py-2 pe-3 text-end tabular-nums">{median(b, pair.base)}</td>
              <td className="py-2 pe-3 text-end tabular-nums">{median(b, pair.other)}</td>
              <td className="py-2 pe-5">{gap(b)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A bucket's side for a retailer, or null when the API left it out: not a count of zero. */
function side(b: Bucket, id: string): Side | null {
  return b.sides[id] ?? null;
}
