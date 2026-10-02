'use client';

import { useTranslations } from 'next-intl';
import { useId, useState, type FormEvent, type ReactNode } from 'react';
import type { Schemas } from '@/lib/api/types';
import { isPrice, toggle, type ExploreState } from '@/lib/explore';
import { RetailerDot } from '../ui/retailer-dot';

type Facets = Schemas['ProductPage']['facets'];
type Facet = Schemas['FacetCount'];

const SHORT_LIST = 8;

/**
 * The filter rail: shop, sold-at, brand, category and price. Every count is the API's facet count
 * for the current filters; the sold-at options have no counts because the API has none for them.
 */
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
    <div className="space-y-5 text-[13px]">
      <Group title={t('retailer')} hint={t('retailerHint')}>
        <Checks
          facet={facets?.retailer ?? []}
          selected={state.retailer}
          label={(k) => name(k)}
          lead={(k, i) => <RetailerDot id={k} index={i} />}
          badge={(k) => {
            const i = state.retailer.indexOf(k);
            return pair && i >= 0 ? String(i + 1) : null;
          }}
          onToggle={(k) => update({ retailer: toggle(state.retailer, k) })}
        />
      </Group>
      <SoldAt value={state.matched} onChange={(matched) => update({ matched })} />
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
    <fieldset aria-describedby={hint ? id : undefined} className="min-w-0">
      <legend className="text-[11.5px] font-semibold tracking-[0.05em] text-ink-3 uppercase">{title}</legend>
      {hint && (
        <p id={id} className="mt-1 text-xs text-ink-3">
          {hint}
        </p>
      )}
      <div className="mt-1.5">{children}</div>
    </fieldset>
  );
}

/**
 * Facet values by count, largest first, each with its count. A selected value the current
 * results no longer contain stays listed (count 0) so it can still be unticked.
 */
function Checks({
  facet,
  selected,
  label = (k) => k,
  lead,
  badge,
  onToggle,
}: {
  facet: Facet[];
  selected: string[];
  label?: (key: string) => string;
  /** Something drawn before the label, e.g. the shop's dot. */
  lead?: (key: string, index: number) => ReactNode;
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
      <ul className="space-y-0.5">
        {shown.map((f, i) => {
          const on = selected.includes(f.key);
          const b = badge?.(f.key);
          return (
            <li key={f.key}>
              <label
                className={`flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 hover:bg-surface-2 ${
                  on ? 'font-medium text-ink' : 'text-ink-2'
                }`}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => onToggle(f.key)}
                  className="size-4 accent-ink"
                />
                {lead?.(f.key, i)}
                <span className="min-w-0 flex-1 truncate" dir="auto">
                  {label(f.key)}
                </span>
                {b && (
                  <span className="pill bg-ink px-1.5 text-surface tabular-nums" aria-hidden>
                    {b}
                  </span>
                )}
                <span className="text-xs font-normal text-ink-3 tabular-nums">{f.count}</span>
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
          className="mt-1 px-1 text-xs text-ink-3 hover:text-ink hover:underline focus-visible:outline-2"
        >
          {all ? t('fewer_facets') : t('more_facets', { n: rows.length })}
        </button>
      )}
    </>
  );
}

/** Sold at both shops (the API's `matched`), one shop only, or any. */
function SoldAt({
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
    <Group title={t('matched')} hint={t('matchedHint')}>
      <div className="space-y-0.5">
        {opts.map(([v, text]) => (
          <label
            key={v}
            className={`flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 hover:bg-surface-2 ${
              value === v ? 'font-medium text-ink' : 'text-ink-2'
            }`}
          >
            <input
              type="radio"
              name={name}
              checked={value === v}
              onChange={() => onChange(v)}
              className="size-4 accent-ink"
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
        <div className="flex items-end gap-1.5">
          {(
            [
              [ids.min, t('priceMin'), lo, setLo],
              [ids.max, t('priceMax'), hi, setHi],
            ] as const
          ).map(([id, label, v, set]) => (
            <div key={id} className="flex min-w-0 flex-1 flex-col gap-1">
              <label htmlFor={id} className="text-xs text-ink-3">
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
                className="w-full field px-2 py-1 text-[13px] tabular-nums focus-visible:outline-2"
              />
            </div>
          ))}
          <button type="submit" className="btn px-2.5 py-1 text-[13px] focus-visible:outline-2">
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
