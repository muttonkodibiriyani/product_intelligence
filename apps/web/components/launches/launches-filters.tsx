'use client';

import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Schemas } from '@/lib/api/types';
import { EVIDENCE_STATES, type LaunchEvidenceRow, type LaunchEvidenceState } from '@/lib/launch-evidence';
import { EMPTY_LAUNCHES, type LaunchesState } from '@/lib/launches';

const AVAILABILITY: Schemas['AvailabilityState'][] = [
  'in_stock',
  'low_stock',
  'out_of_stock',
  'not_deliverable',
  'removed',
  'not_observed',
  'blocked',
  'unknown',
];

const values = (rows: readonly LaunchEvidenceRow[], read: (row: LaunchEvidenceRow) => readonly string[]) =>
  [...new Set(rows.flatMap(read).filter(Boolean))].sort((a, b) => a.localeCompare(b));

const toggle = <T extends string>(selected: readonly T[], value: T): T[] =>
  selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value];

/** All Launches filters. Native fieldsets/details keep the rail usable by keyboard and on small screens. */
export function LaunchesFilters({
  state,
  rows,
  retailers,
  currency,
  end,
  update,
}: {
  state: LaunchesState;
  rows: readonly LaunchEvidenceRow[];
  retailers: readonly Pick<Schemas['RetailerView'], 'id' | 'name'>[];
  currency: string;
  end: string;
  update: (next: Partial<LaunchesState>) => void;
}) {
  const t = useTranslations('launches.filters');
  const brands = values(rows, (row) => (row.brand.value ? [row.brand.value] : []));
  const categories = values(rows, (row) => row.category.value ?? []);
  const active =
    state.retailer.length +
    state.brand.length +
    state.category.length +
    state.availability.length +
    state.evidence.length +
    [
      state.dateFrom,
      state.dateTo,
      state.priceMin,
      state.priceMax,
      state.discountMin,
      state.size,
      state.color,
      state.shade,
    ].filter(Boolean).length;
  const clear = () =>
    update({
      retailer: EMPTY_LAUNCHES.retailer,
      brand: EMPTY_LAUNCHES.brand,
      category: EMPTY_LAUNCHES.category,
      dateFrom: '',
      dateTo: '',
      priceMin: '',
      priceMax: '',
      discountMin: '',
      availability: [],
      size: '',
      color: '',
      shade: '',
      evidence: [],
    });

  return (
    <details className="panel group" open>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 font-medium focus-visible:outline-2">
        <span>{t('title')}</span>
        {active > 0 && <span className="pill tabular-nums">{active}</span>}
        <span aria-hidden className="ms-auto transition-transform group-open:rotate-180">
          ▾
        </span>
      </summary>
      <div className="grid gap-4 border-t border-line px-4 py-4 sm:grid-cols-2 xl:grid-cols-4">
        <Checks
          title={t('retailer')}
          options={retailers.map((retailer) => ({ value: retailer.id, label: retailer.name }))}
          selected={state.retailer}
          onToggle={(retailer) => update({ retailer: toggle(state.retailer, retailer) })}
        />
        <Checks
          title={t('brand')}
          options={brands.map((brand) => ({ value: brand, label: brand }))}
          selected={state.brand}
          empty={t('awaitingEvidence')}
          onToggle={(brand) => update({ brand: toggle(state.brand, brand) })}
        />
        <Checks
          title={t('category')}
          options={categories.map((category) => ({ value: category, label: category }))}
          selected={state.category}
          empty={t('awaitingEvidence')}
          onToggle={(category) => update({ category: toggle(state.category, category) })}
        />
        <Group title={t('date')}>
          <div className="grid grid-cols-2 gap-2">
            <TextInput
              type="date"
              label={t('from')}
              value={state.dateFrom}
              max={state.dateTo || end}
              onChange={(dateFrom) => update({ dateFrom })}
            />
            <TextInput
              type="date"
              label={t('to')}
              value={state.dateTo}
              min={state.dateFrom}
              max={end}
              onChange={(dateTo) => update({ dateTo })}
            />
          </div>
        </Group>
        <Group title={t('price', { currency: currency || '–' })}>
          <div className="grid grid-cols-2 gap-2">
            <TextInput
              type="number"
              label={t('minimum')}
              value={state.priceMin}
              min="0"
              step="0.01"
              onChange={(priceMin) => update({ priceMin })}
            />
            <TextInput
              type="number"
              label={t('maximum')}
              value={state.priceMax}
              min="0"
              step="0.01"
              onChange={(priceMax) => update({ priceMax })}
            />
          </div>
        </Group>
        <Group title={t('discount')}>
          <TextInput
            type="number"
            label={t('minimumPct')}
            value={state.discountMin}
            min="0"
            max="100"
            step="0.1"
            onChange={(discountMin) => update({ discountMin })}
          />
        </Group>
        <Checks
          title={t('availability')}
          options={AVAILABILITY.map((availability) => ({
            value: availability,
            label: t(`availabilityStates.${availability}`),
          }))}
          selected={state.availability}
          onToggle={(availability) => update({ availability: toggle(state.availability, availability) })}
        />
        <Group title={t('attributes')}>
          <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-1">
            <TextInput label={t('size')} value={state.size} onChange={(size) => update({ size })} />
            <TextInput label={t('color')} value={state.color} onChange={(color) => update({ color })} />
            <TextInput label={t('shade')} value={state.shade} onChange={(shade) => update({ shade })} />
          </div>
        </Group>
        <Checks
          title={t('evidence')}
          options={EVIDENCE_STATES.map((evidence) => ({
            value: evidence,
            label: t(`evidenceStates.${evidence}`),
          }))}
          selected={state.evidence}
          onToggle={(evidence) => update({ evidence: toggle<LaunchEvidenceState>(state.evidence, evidence) })}
        />
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-ink-3">
        <p>{t('hint')}</p>
        <button
          type="button"
          onClick={clear}
          disabled={active === 0}
          className="btn shrink-0 focus-visible:outline-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t('clear')}
        </button>
      </div>
    </details>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="min-w-0">
      <legend className="text-[11.5px] font-semibold tracking-[0.05em] text-ink-3 uppercase">{title}</legend>
      <div className="mt-2">{children}</div>
    </fieldset>
  );
}

function Checks<T extends string>({
  title,
  options,
  selected,
  empty,
  onToggle,
}: {
  title: string;
  options: readonly { value: T; label: string }[];
  selected: readonly T[];
  empty?: string;
  onToggle: (value: T) => void;
}) {
  return (
    <Group title={title}>
      {options.length === 0 ? (
        <p className="text-xs text-ink-3">{empty}</p>
      ) : (
        <div className="max-h-32 space-y-1 overflow-y-auto pe-1">
          {options.map((option) => (
            <label
              key={option.value}
              className="flex cursor-pointer items-start gap-2 text-[13px] text-ink-2"
            >
              <input
                type="checkbox"
                checked={selected.includes(option.value)}
                onChange={() => onToggle(option.value)}
                className="mt-0.5 size-4 shrink-0 accent-ink"
              />
              <span dir="auto">{option.label}</span>
            </label>
          ))}
        </div>
      )}
    </Group>
  );
}

function TextInput({
  label,
  value,
  onChange,
  type = 'search',
  ...props
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: 'search' | 'number' | 'date';
  min?: string;
  max?: string;
  step?: string;
}) {
  return (
    <label className="grid min-w-0 gap-1 text-xs text-ink-3">
      <span>{label}</span>
      <input
        {...props}
        type={type}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        className="input min-w-0 text-ink"
      />
    </label>
  );
}
