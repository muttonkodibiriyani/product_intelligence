'use client';

import { useTranslations } from 'next-intl';
import { useId, useState, type FormEvent, type ReactNode } from 'react';
import type { Schemas } from '@/lib/api/types';
import { isPrice, toggle, type ExploreState } from '@/lib/explore';

type Facets = Schemas['ProductPage']['facets'];
type Facet = Schemas['FacetCount'];

const SHORT_LIST = 8;

/** Facet filters. Counts are the API's, for the current filters. */
export function Filters({
  state,
  facets,
  currency,
  name,
  update,
}: {
  state: ExploreState;
  facets: Facets | null;
  currency: string;
  name: (id: string) => string;
  update: (next: Partial<ExploreState>) => void;
}) {
  const t = useTranslations('explore');
  const pair = state.retailer.length === 2;
  return (
    <div className="space-y-6 text-sm">
      <Group title={t('retailer')} hint={t('retailerHint')}>
        <Checks
          facet={facets?.retailer ?? []}
          selected={state.retailer}
          label={(k) => name(k)}
          badge={(k) => {
            const i = state.retailer.indexOf(k);
            return pair && i >= 0 ? String(i + 1) : null;
          }}
          onToggle={(k) => update({ retailer: toggle(state.retailer, k) })}
        />
      </Group>
      <Group title={t('brand')}>
        <Checks
          facet={facets?.brand ?? []}
          selected={state.brand}
          onToggle={(k) => update({ brand: toggle(state.brand, k) })}
        />
      </Group>
      <Group title={t('category')}>
        <Checks
          facet={facets?.category ?? []}
          selected={state.category}
          onToggle={(k) => update({ category: toggle(state.category, k) })}
        />
      </Group>
      <Matched value={state.matched} onChange={(matched) => update({ matched })} />
      <PriceRange
        key={`${state.priceMin}-${state.priceMax}`}
        min={state.priceMin}
        max={state.priceMax}
        currency={currency}
        onApply={(priceMin, priceMax) => update({ priceMin, priceMax })}
      />
    </div>
  );
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  const id = useId();
  return (
    <fieldset aria-describedby={hint ? id : undefined}>
      <legend className="font-semibold">{title}</legend>
      {hint && (
        <p id={id} className="mt-1 text-xs text-ink-2">
          {hint}
        </p>
      )}
      <div className="mt-2">{children}</div>
    </fieldset>
  );
}

/**
 * Facet values by count, largest first. A selected value the current results no longer contain
 * stays listed (count 0) so it can still be unticked.
 */
function Checks({
  facet,
  selected,
  label = (k) => k,
  badge,
  onToggle,
}: {
  facet: Facet[];
  selected: string[];
  label?: (key: string) => string;
  badge?: (key: string) => string | null;
  onToggle: (key: string) => void;
}) {
  const t = useTranslations('explore');
  const [all, setAll] = useState(false);
  const known = new Set(facet.map((f) => f.key));
  const rows = [
    ...[...facet].sort((a, b) => b.count - a.count || a.key.localeCompare(b.key)),
    ...selected.filter((k) => !known.has(k)).map((key) => ({ key, count: 0 })),
  ];
  const shown = all ? rows : rows.filter((r, i) => i < SHORT_LIST || selected.includes(r.key));
  return (
    <>
      <ul className="space-y-1">
        {shown.map((f) => {
          const b = badge?.(f.key);
          return (
            <li key={f.key}>
              <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-surface">
                <input
                  type="checkbox"
                  checked={selected.includes(f.key)}
                  onChange={() => onToggle(f.key)}
                  className="size-4 accent-accent"
                />
                <span className="min-w-0 flex-1 truncate" dir="auto">
                  {label(f.key)}
                </span>
                {b && (
                  <span className="rounded bg-accent px-1 text-xs text-surface tabular-nums" aria-hidden>
                    {b}
                  </span>
                )}
                <span className="text-xs text-ink-2 tabular-nums">{f.count}</span>
              </label>
            </li>
          );
        })}
      </ul>
      {rows.length > SHORT_LIST && (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll((a) => !a)}
          className="mt-1 px-1 text-xs text-accent hover:underline focus-visible:outline-2"
        >
          {all ? t('fewer_facets') : t('more_facets', { n: rows.length })}
        </button>
      )}
    </>
  );
}

function Matched({
  value,
  onChange,
}: {
  value: ExploreState['matched'];
  onChange: (v: ExploreState['matched']) => void;
}) {
  const t = useTranslations('explore');
  const name = useId();
  const opts = [
    ['any', t('matchedAny')],
    ['yes', t('matchedYes')],
    ['no', t('matchedNo')],
  ] as const;
  return (
    <Group title={t('matched')}>
      <div className="space-y-1">
        {opts.map(([v, text]) => (
          <label key={v} className="flex cursor-pointer items-center gap-2 px-1 py-0.5">
            <input
              type="radio"
              name={name}
              checked={value === v}
              onChange={() => onChange(v)}
              className="size-4 accent-accent"
            />
            {text}
          </label>
        ))}
      </div>
    </Group>
  );
}

function PriceRange({
  min,
  max,
  currency,
  onApply,
}: {
  min: string;
  max: string;
  currency: string;
  onApply: (min: string, max: string) => void;
}) {
  const t = useTranslations('explore');
  const ids = { min: useId(), max: useId(), err: useId() };
  const [lo, setLo] = useState(min);
  const [hi, setHi] = useState(max);
  const [tried, setTried] = useState(false);
  const bad = !isPrice(lo.trim()) || !isPrice(hi.trim());
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!bad) onApply(lo.trim(), hi.trim());
  };
  return (
    <form onSubmit={submit} noValidate>
      <Group title={t('price', { currency: currency || '–' })}>
        <div className="flex items-end gap-2">
          {(
            [
              [ids.min, t('priceMin'), lo, setLo],
              [ids.max, t('priceMax'), hi, setHi],
            ] as const
          ).map(([id, label, v, set]) => (
            <div key={id} className="flex min-w-0 flex-1 flex-col gap-1">
              <label htmlFor={id} className="text-xs text-ink-2">
                {label}
              </label>
              <input
                id={id}
                inputMode="decimal"
                dir="ltr"
                value={v}
                maxLength={19}
                aria-invalid={tried && bad}
                aria-describedby={tried && bad ? ids.err : undefined}
                onChange={(e) => set(e.target.value)}
                className="w-full rounded border border-line bg-surface px-2 py-1 tabular-nums focus-visible:outline-2"
              />
            </div>
          ))}
          <button
            type="submit"
            className="rounded border border-line bg-surface px-2 py-1 hover:bg-surface-2 focus-visible:outline-2"
          >
            {t('apply')}
          </button>
        </div>
        {tried && bad && (
          <p id={ids.err} className="mt-1 text-xs text-danger">
            {t('priceInvalid')}
          </p>
        )}
      </Group>
    </form>
  );
}
