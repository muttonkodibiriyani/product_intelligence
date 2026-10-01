'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { useSyncExternalStore } from 'react';
import type { Schemas } from '@/lib/api/types';
import { Price } from '../ui/money';
import { GapView } from '../ui/pair';
import { productHref, Size } from './product-table';
import { RowThumb } from './row-thumb';

type Card = Schemas['ProductCard'];
export type View = 'grid' | 'list';

/** Retailer badges take the chart series' tones, in column order, so a retailer reads the same everywhere. */
const TONE = [
  'bg-blush text-blush-ink',
  'bg-sky text-sky-ink',
  'bg-lav text-lav-ink',
  'bg-mint text-mint-ink',
];

/**
 * Products as image-first cards: the photo leads, then brand, name, size and a price per
 * retailer. The whole card opens the product; the list (`ProductTable`) is the dense view.
 */
export function ProductGrid({
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
  const tp = useTranslations('product');
  const locale = useLocale();
  return (
    <ul aria-label={t('results')} className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
      {items.map((c) => {
        const offered = retailers.filter((r) => r in c.prices);
        return (
          <li
            key={c.id}
            className="group relative flex min-w-0 flex-col overflow-hidden panel transition-shadow hover:shadow-md focus-within:shadow-md"
          >
            <div className="aspect-square border-b border-line bg-white p-3">
              <RowThumb url={c.image} label={t('noImage')} px={320} cls="size-full rounded-[6px]" />
            </div>
            <div className="flex flex-1 flex-col p-3">
              <span className="truncate text-xs text-ink-2" dir="auto">
                {c.brand}
              </span>
              <Link
                href={productHref(locale, c.id, from)}
                className="mt-0.5 line-clamp-2 text-sm font-medium text-ink after:absolute after:inset-0 group-hover:underline focus-visible:outline-2"
                dir="auto"
              >
                {c.name}
              </Link>
              <span className="mt-1 truncate text-xs text-ink-2">
                {c.size && <Size size={c.size} />}
                {c.size && c.category.length > 0 && ' · '}
                <span dir="auto">{c.category.at(-1)}</span>
              </span>
              {offered.length === 0 && <p className="mt-auto pt-3 text-sm text-ink-2">{t('notOffered')}</p>}
              <dl className="mt-auto space-y-1 pt-3 text-sm empty:hidden">
                {offered.map((r) => (
                  <div key={r} className="flex items-center justify-between gap-2">
                    <dt
                      className={`truncate rounded-full px-2 py-0.5 text-xs ${TONE[retailers.indexOf(r) % TONE.length]}`}
                    >
                      {name(r)}
                    </dt>
                    <dd className="whitespace-nowrap font-medium tabular-nums">
                      <Price
                        of={{ price: c.prices[r] }}
                        locale={locale}
                        fallback={<span className="font-normal text-ink-2">{tp('noPrice')}</span>}
                      />
                    </dd>
                  </div>
                ))}
              </dl>
              {pair && c.gap && (
                <div className="mt-2 border-t border-line pt-2 text-xs">
                  <GapView pair={c.gap} name={name} />
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// The reader's last choice of view, kept on this device. Grid unless they picked the list.
const KEY = 'pi.explore.view';
const listeners = new Set<() => void>();
let picked: View | null = null; // when storage is unavailable (private mode), for this page
function read(): View {
  try {
    return localStorage.getItem(KEY) === 'list' ? 'list' : 'grid';
  } catch {
    return picked ?? 'grid';
  }
}
function subscribe(fn: () => void) {
  listeners.add(fn);
  window.addEventListener('storage', fn);
  return () => {
    listeners.delete(fn);
    window.removeEventListener('storage', fn);
  };
}

export function useView(): [View, (v: View) => void] {
  const view = useSyncExternalStore(subscribe, read, () => 'grid' as const);
  const set = (v: View) => {
    picked = v;
    try {
      localStorage.setItem(KEY, v);
    } catch {
      // Private mode: the choice lasts for this page only.
    }
    listeners.forEach((fn) => fn());
  };
  return [view, set];
}

/** Grid / List: two pressed-state buttons. */
export function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const t = useTranslations('explore');
  return (
    <div
      role="group"
      aria-label={t('view')}
      className="inline-flex rounded-ctl border border-line-3 bg-surface p-0.5"
    >
      {(['grid', 'list'] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={view === v}
          onClick={() => onChange(v)}
          className={`rounded-[5px] px-2.5 py-1 text-sm focus-visible:outline-2 ${
            view === v ? 'bg-ink text-surface' : 'text-ink-2 hover:text-ink'
          }`}
        >
          {t(v === 'grid' ? 'viewGrid' : 'viewList')}
        </button>
      ))}
    </div>
  );
}
