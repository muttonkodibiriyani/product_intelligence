'use client';

import { useTranslations } from 'next-intl';
import { useId, useState, type FormEvent } from 'react';
import { activeFilterCount, EMPTY, hasPair, SORTS, type ExploreState, type ProductSort } from '@/lib/explore';

/** Search, sort and the retailer pair the gap is measured between. */
export function Toolbar({
  state,
  update,
  name,
}: {
  state: ExploreState;
  update: (next: Partial<ExploreState>) => void;
  name: (id: string) => string;
}) {
  const t = useTranslations('explore');
  const ids = { q: useId(), sort: useId(), sortHint: useId() };
  // The parent keys this by the URL value, so Back or "clear" resets the box.
  const [q, setQ] = useState(state.q);
  const pair = hasPair(state) ? (state.retailer as [string, string]) : null;
  const names = pair ? { base: name(pair[0]), other: name(pair[1]) } : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    update({ q: q.trim().slice(0, 120) });
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <form role="search" onSubmit={submit} className="flex min-w-0 flex-1 basis-64 gap-2">
        <label htmlFor={ids.q} className="sr-only">
          {t('searchLabel')}
        </label>
        <input
          id={ids.q}
          type="search"
          name="q"
          value={q}
          maxLength={120}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('searchPlaceholder')}
          className="min-w-0 flex-1 field focus-visible:outline-2"
        />
        <button type="submit" className="btn focus-visible:outline-2">
          {t('search')}
        </button>
      </form>

      <div className="flex items-center gap-2">
        <label htmlFor={ids.sort} className="text-[13px] text-ink-2">
          {t('sort')}
        </label>
        <select
          id={ids.sort}
          value={state.sort}
          aria-describedby={pair ? undefined : ids.sortHint}
          onChange={(e) => update({ sort: e.target.value as ProductSort })}
          className="field focus-visible:outline-2"
        >
          {SORTS.map((s) => (
            <option key={s} value={s} disabled={(s === 'gap' || s === 'gap_asc') && !pair}>
              {(s === 'gap' || s === 'gap_asc') && !(pair && names)
                ? t(`sortsNoPair.${s}`)
                : t(`sorts.${s}`, { other: names?.other ?? '' })}
            </option>
          ))}
        </select>
        {!pair && (
          <span id={ids.sortHint} className="sr-only">
            {t('gapNeedsPair')}
          </span>
        )}
      </div>

      {pair && names && (
        <div className="flex items-center gap-2 rounded-ctl border border-line-3 bg-surface px-3 py-1.5 text-[13px]">
          <span>{t('pair', names)}</span>
          <button
            type="button"
            onClick={() => update({ retailer: [pair[1], pair[0]] })}
            className="rounded-md px-1.5 text-accent hover:bg-surface-2 focus-visible:outline-2"
          >
            {t('swap')}
          </button>
        </div>
      )}
    </div>
  );
}

type Chip = { key: string; label: string; remove: Partial<ExploreState> };

/** Every active filter as a removable chip, with "Clear all" after them. */
export function ActiveChips({
  state,
  name,
  update,
}: {
  state: ExploreState;
  name: (id: string) => string;
  update: (next: Partial<ExploreState>) => void;
}) {
  const t = useTranslations('explore.chips');
  const te = useTranslations('explore');
  if (activeFilterCount(state) === 0) return null;
  const chips: Chip[] = [
    ...(state.q ? [{ key: 'q', label: t('search', { value: state.q }), remove: { q: '' } }] : []),
    ...state.retailer.map((v) => ({
      key: `retailer:${v}`,
      label: t('shop', { value: name(v) }),
      remove: { retailer: state.retailer.filter((x) => x !== v) },
    })),
    ...(state.matched !== 'any'
      ? [
          {
            key: 'matched',
            label: t(state.matched === 'yes' ? 'soldBoth' : 'soldOne'),
            remove: { matched: 'any' as const },
          },
        ]
      : []),
    ...state.brand.map((v) => ({
      key: `brand:${v}`,
      label: t('brand', { value: v }),
      remove: { brand: state.brand.filter((x) => x !== v) },
    })),
    ...state.category.map((v) => ({
      key: `category:${v}`,
      label: t('category', { value: v }),
      remove: { category: state.category.filter((x) => x !== v) },
    })),
    ...(state.priceMin
      ? [{ key: 'min', label: t('priceMin', { value: state.priceMin }), remove: { priceMin: '' } }]
      : []),
    ...(state.priceMax
      ? [{ key: 'max', label: t('priceMax', { value: state.priceMax }), remove: { priceMax: '' } }]
      : []),
    ...state.availability.map((v) => ({
      key: `availability:${v}`,
      label: t(`stock.${v}`),
      remove: { availability: state.availability.filter((x) => x !== v) },
    })),
    ...(state.unavailableBrands
      ? [
          {
            key: 'unavailableBrands',
            label: t(`unavailable.${state.unavailableBrands}`),
            remove: { unavailableBrands: null },
          },
        ]
      : []),
  ];
  return (
    <ul aria-label={t('label')} className="flex flex-wrap items-center gap-1.5">
      {chips.map((c) => (
        <li key={c.key}>
          <button
            type="button"
            onClick={() => update(c.remove)}
            className="inline-flex items-center gap-1.5 rounded-full border border-line-3 bg-surface px-2.5 py-0.5 text-xs text-ink hover:bg-surface-2 focus-visible:outline-2"
          >
            <span dir="auto">{c.label}</span>
            <span aria-hidden className="text-ink-3">
              ×
            </span>
            <span className="sr-only">{t('remove')}</span>
          </button>
        </li>
      ))}
      <li>
        <button
          type="button"
          onClick={() => update(EMPTY)}
          className="px-1.5 py-0.5 text-xs text-ink-2 underline-offset-2 hover:underline focus-visible:outline-2"
        >
          {te('clear')}
        </button>
      </li>
    </ul>
  );
}
