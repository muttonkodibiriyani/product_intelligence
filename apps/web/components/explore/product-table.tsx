'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { Money } from '../ui/money';
import { GapView, MatchLabel } from '../ui/pair';

type Card = Schemas['ProductCard'];

/** The URL of a product page; `from` carries the list's query so "Back to products" restores it. */
export function productHref(locale: string, id: string, from = ''): string {
  const p = new URLSearchParams({ id });
  if (from) p.set('from', from.replace(/^\?/, ''));
  return `/${locale}/product/?${p.toString()}`;
}

/** Dense list of products: one row each, a price column per retailer, the pair's gap last. */
export function ProductTable({
  items,
  retailers,
  pair,
  name,
  from,
}: {
  items: Card[];
  retailers: string[];
  pair: [string, string] | null;
  name: (id: string) => string;
  from: string;
}) {
  const t = useTranslations('explore');
  const locale = useLocale();
  const th = 'px-3 py-2 text-start font-medium text-ink-2 whitespace-nowrap';
  return (
    <div className="relative overflow-x-auto rounded border border-line bg-surface">
      <table className="w-full text-sm">
        <caption className="sr-only">{t('results')}</caption>
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${th} sticky start-0 bg-surface`}>
              {t('colProduct')}
            </th>
            {retailers.map((r) => (
              <th key={r} scope="col" className={`${th} text-end`}>
                {name(r)}
              </th>
            ))}
            <th scope="col" className={th}>
              {t('colMatch')}
            </th>
            {pair && (
              <th scope="col" className={th}>
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
              className="group border-t border-line align-top first:border-t-0 hover:bg-surface-2"
            >
              <th
                scope="row"
                className="sticky start-0 min-w-44 bg-surface px-3 py-2 text-start font-normal group-hover:bg-surface-2"
              >
                <span className="block text-xs text-ink-2" dir="auto">
                  {c.brand}
                </span>
                <Link
                  href={productHref(locale, c.id, from)}
                  className="block max-w-72 font-medium text-ink hover:underline focus-visible:outline-2"
                  dir="auto"
                >
                  {c.name}
                </Link>
                <span className="block text-xs text-ink-2">
                  {c.size && <Size size={c.size} />}
                  {c.size && c.category.length > 0 && ' · '}
                  <span dir="auto">{c.category.join(' › ')}</span>
                </span>
              </th>
              {retailers.map((r) => (
                <td key={r} className="px-3 py-2 text-end">
                  <Price card={c} retailer={r} locale={locale} />
                </td>
              ))}
              <td className="px-3 py-2">
                <Matches card={c} pair={pair} />
              </td>
              {pair && (
                <td className="px-3 py-2">
                  {c.gap ? <GapView pair={c.gap} name={name} /> : <span className="text-ink-2">–</span>}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Size({ size }: { size: Schemas['Size'] }) {
  return (
    <bdi dir="ltr" className="tabular-nums">
      {size.value} {size.unit}
    </bdi>
  );
}

function Price({ card, retailer, locale }: { card: Card; retailer: string; locale: string }) {
  const t = useTranslations('explore');
  const tp = useTranslations('product');
  if (!(retailer in card.prices))
    return <span className="whitespace-nowrap text-ink-2">{t('notOffered')}</span>;
  const m = card.prices[retailer];
  return m ? <Money m={m} locale={locale} /> : <span className="text-ink-2">{tp('noPrice')}</span>;
}

/** The pair's match when a pair is picked; otherwise the first match and how many more. */
function Matches({ card, pair }: { card: Card; pair: [string, string] | null }) {
  const t = useTranslations('match');
  const relevant = pair ? card.matches.filter((m) => pair.includes(m.a) && pair.includes(m.b)) : card.matches;
  const first = relevant[0];
  if (!first) return <span className="text-ink-2">{t('none')}</span>;
  return (
    <span className="flex flex-col">
      <MatchLabel m={first} />
      {relevant.length > 1 && <span className="text-xs text-ink-2 tabular-nums">+{relevant.length - 1}</span>}
    </span>
  );
}
