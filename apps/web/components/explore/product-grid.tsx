'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useSyncExternalStore } from 'react';
import type { Schemas } from '@/lib/api/types';
import { verdictOf } from '@/lib/verdict';
import { ProductCard, useVerdictChip, type PriceLine } from '../ui/product-card';
import { productHref } from './product-table';

type Card = Schemas['ProductCard'];
export type View = 'grid' | 'list';

/**
 * The price lines of a product card: one per shop in column order. A shop without the product
 * reads "Not sold"; when the pair's sizes differ, each side shows its own size.
 */
export function priceLines(c: Card, retailers: readonly string[], name: (id: string) => string): PriceLine[] {
  const sizes = c.gap?.sizeLabels;
  return retailers.map((r) => ({
    retailer: r,
    label: name(r),
    notSold: !(r in c.prices),
    price: c.prices[r],
    priceFlag: c.priceFlags?.[r],
    size: sizes && c.gap ? (r === c.gap.base ? sizes[0] : r === c.gap.other ? sizes[1] : null) : null,
  }));
}

/**
 * Products as image-first cards: the photo leads, then brand, name, size and a price per shop,
 * with the pair's verdict on the photo. The list (`ProductTable`) is the dense view.
 */
export function ProductGrid({
  items,
  retailers,
  name,
  from,
}: {
  items: Card[];
  retailers: string[];
  pair?: [string, string] | null;
  name: (id: string) => string;
  from: string;
}) {
  const t = useTranslations('explore');
  const locale = useLocale();
  const chip = useVerdictChip(name);
  return (
    <ul aria-label={t('results')} className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
      {items.map((c) => (
        <li key={c.id} className="min-w-0">
          <ProductCard
            href={productHref(locale, c.id, from)}
            image={c.image}
            brand={c.brand}
            name={c.name}
            size={c.size}
            category={c.category.at(-1)}
            lines={priceLines(c, retailers, name)}
            chip={chip(verdictOf(c))}
          />
        </li>
      ))}
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

/** Grid / List: a segmented control of two pressed-state buttons. */
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
          className={`rounded-[6px] px-2.5 py-0.5 text-[13px] focus-visible:outline-2 ${
            view === v ? 'bg-ink text-surface' : 'text-ink-2 hover:text-ink'
          }`}
        >
          {t(v === 'grid' ? 'viewGrid' : 'viewList')}
        </button>
      ))}
    </div>
  );
}
