'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { cellState, freshnessOf, missingFields, type SourceFreshness } from '@/lib/source-freshness';
import { gapBar, gapScale } from '@/lib/verdict';
import { MissingFields, SourceBadge, StateBadge } from '../ui/freshness';
import { Known } from '../ui/known';
import { Money, Pct, Price as PriceOf } from '../ui/money';
import { MatchReviewLabel, SizeText } from '../ui/product-card';
import { monogram, RowThumb } from './row-thumb';

type Card = Schemas['ProductCard'];

/** Where the product page's Back goes; the explorer when not set. */
export type BackTo = 'compare' | 'overlap' | 'promotions' | 'launches';

/** The URL of a product page; `from` carries the list's query so Back restores it. */
export function productHref(locale: string, id: string, from = '', back?: BackTo): string {
  const p = new URLSearchParams({ id, ...(back ? { back } : {}) });
  if (from) p.set('from', from.replace(/^\?/, ''));
  return `/${locale}/product/?${p.toString()}`;
}

/**
 * Dense list of products: the thumbnail and name first, a right-aligned price column per shop in
 * tabular numerals, and, with a pair, the gap as a signed number beside a bar centred on zero.
 */
export function ProductTable({
  items,
  retailers,
  pair,
  name,
  from,
  sources = null,
}: {
  items: Card[];
  retailers: string[];
  pair: [string, string] | null;
  name: (id: string) => string;
  from: string;
  /** Each retailer's own source state (lib/source-freshness); none until /meta has loaded. */
  sources?: readonly SourceFreshness[] | null;
}) {
  const t = useTranslations('explore');
  const tc = useTranslations('productCard');
  const locale = useLocale();
  const scale = gapScale(items);
  const th = 'th whitespace-nowrap';
  return (
    <div className="relative overflow-x-auto panel">
      <table className="w-full text-sm">
        <caption className="sr-only">{t('results')}</caption>
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${th} sticky start-0 bg-surface text-start`}>
              {t('colProduct')}
            </th>
            {retailers.map((r) => (
              <th key={r} scope="col" className={`${th} text-end`}>
                {name(r)}
                {sources && (
                  <span className="mt-1 block font-normal">
                    <SourceBadge source={freshnessOf(sources, r)} />
                  </span>
                )}
              </th>
            ))}
            {pair && (
              <th scope="col" className={`${th} text-end`}>
                {t('colGap')}
                <span className="block text-xs font-normal">
                  {t('gapHeader', { base: name(pair[0]), other: name(pair[1]) })}
                </span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr
              key={c.id}
              className="group border-t border-line-2 align-middle first:border-t-0 hover:bg-surface-2"
            >
              <th
                scope="row"
                className="sticky start-0 min-w-56 bg-surface px-3 py-2 text-start font-normal group-hover:bg-surface-2"
              >
                <div className="flex items-center gap-3">
                  <RowThumb
                    url={c.image}
                    label={tc('noImage')}
                    monogram={monogram(c.brand)}
                    cls="size-11 shrink-0 rounded-[6px] bg-surface-2"
                  />
                  <div className="min-w-0">
                    {c.brand && (
                      <span className="block truncate text-xs text-ink-3" dir="auto">
                        {c.brand}
                      </span>
                    )}
                    <Link
                      href={productHref(locale, c.id, from)}
                      className="block max-w-72 leading-tight font-medium text-ink hover:underline focus-visible:outline-2"
                      dir="auto"
                    >
                      {c.name}
                    </Link>
                    <span className="block truncate text-xs text-ink-3">
                      {c.size && <SizeText size={c.size} />}
                      {c.size && c.category.length > 0 && ' · '}
                      <span dir="auto">{c.category.join(' › ')}</span>
                    </span>
                    <MatchReviewLabel review={c.matchReview} className="mt-1" />
                    <MissingFields fields={missingFields(c)} className="mt-0.5" />
                  </div>
                </div>
              </th>
              {retailers.map((r) => (
                <td key={r} className="px-3 py-2 text-end whitespace-nowrap tabular-nums">
                  <Price card={c} retailer={r} locale={locale} />
                  {sources && <CellBadge card={c} source={freshnessOf(sources, r)} />}
                </td>
              ))}
              {pair && (
                <td className="px-3 py-2 text-end">
                  <GapCell pair={c.gap} name={name} scale={scale} />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The cell's evidence state when it is not the dataset's latest; nothing more for a current price. */
function CellBadge({ card, source }: { card: Card; source: SourceFreshness }) {
  const state = cellState(card, source);
  if (state === 'fresh' || state === 'no_offer' || state === 'no_price') return null;
  return (
    <span className="mt-0.5 block">
      <StateBadge state={state} />
    </span>
  );
}

/** "50 ml": kept for the pages that import it from here. */
export const Size = SizeText;

function Price({ card, retailer, locale }: { card: Card; retailer: string; locale: string }) {
  const t = useTranslations('productCard');
  const tp = useTranslations('product');
  if (!(retailer in card.prices)) return <span className="text-ink-3">{t('notSold')}</span>;
  return (
    <PriceOf
      of={{ price: card.prices[retailer], priceFlag: card.priceFlags?.[retailer] }}
      locale={locale}
      fallback={<span className="text-ink-3">{tp('noPrice')}</span>}
    />
  );
}

/**
 * The pair's gap as the API computed it (other minus base), the bar centred on zero and who is
 * cheaper in words; an uncounted pair says why instead.
 */
function GapCell({ pair, name, scale }: { pair: Card['gap']; name: (id: string) => string; scale: number }) {
  const t = useTranslations('gap');
  const locale = useLocale();
  if (!pair) return <span className="text-ink-3">–</span>;
  const g = pair.gap;
  if (g) {
    const bar = gapBar(g, scale);
    return (
      <span className="inline-flex flex-col items-end gap-0.5">
        <span className="inline-flex items-center gap-2">
          <span className="font-medium">
            <Money m={g.amount} locale={locale} signed />
          </span>
          <span className="gapbar" aria-hidden>
            {bar && <i data-side={bar.side} style={{ width: `${bar.width}%` }} />}
          </span>
        </span>
        <span className="text-xs text-ink-2">
          <Pct v={g.pct} />
          {' · '}
          {g.cheaper === 'equal'
            ? t('equal')
            : t(g.cheaper === 'other' ? 'otherCheaper' : 'otherDearer', { other: name(pair.other) })}
        </span>
      </span>
    );
  }
  if (pair.excludedReason)
    return (
      <span className="inline-flex flex-col items-end gap-0.5">
        <span className="text-ink-2">{t('notCounted')}</span>
        <span className="text-xs text-ink-3">
          <Known t={t} k="excluded" v={pair.excludedReason} />
        </span>
      </span>
    );
  return <span className="text-ink-3">–</span>;
}
