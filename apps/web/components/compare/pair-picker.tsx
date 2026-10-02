'use client';

import { useTranslations } from 'next-intl';
import { useId } from 'react';
import { pick, type CompareState, type GroupBy } from '@/lib/compare';
import { retailerName } from '@/lib/retailers';
import { useMeta } from '../use-meta';

const SELECT = 'min-w-0 field focus-visible:outline-2 disabled:opacity-60';

/** Base, other and grouping. Retailers come from /meta, each by its shop name only. */
export function PairPicker({
  state,
  update,
}: {
  state: CompareState;
  update: (next: Partial<CompareState>) => void;
}) {
  const t = useTranslations('compare');
  const retailers = useMeta().data?.data?.retailers ?? [];
  const id = useId();
  const option = (r: (typeof retailers)[number]) => (
    <option key={r.id} value={r.id}>
      {retailerName(r.id, r.name)}
    </option>
  );
  const side = (s: 'base' | 'other') => (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={`${id}-${s}`} className="text-xs font-medium text-ink-2">
        {t(s === 'base' ? 'base' : 'other')}
      </label>
      <select
        id={`${id}-${s}`}
        value={state[s]}
        disabled={retailers.length === 0}
        onChange={(e) => update(pick(state, s, e.target.value))}
        className={SELECT}
      >
        <option value="">{t('choose')}</option>
        {retailers.map(option)}
      </select>
    </div>
  );
  return (
    <div className="flex flex-wrap items-end gap-3 panel px-5 py-4">
      {side('base')}
      <button
        type="button"
        onClick={() => update({ base: state.other, other: state.base })}
        disabled={!state.base && !state.other}
        className="btn focus-visible:outline-2"
      >
        {t('swap')}
      </button>
      {side('other')}
      <div className="flex min-w-0 flex-col gap-1 sm:ms-auto">
        <label htmlFor={`${id}-group`} className="text-xs font-medium text-ink-2">
          {t('groupBy')}
        </label>
        <select
          id={`${id}-group`}
          value={state.groupBy ?? ''}
          onChange={(e) => update({ groupBy: (e.target.value || null) as GroupBy | null })}
          className={SELECT}
        >
          <option value="">{t('groupNone')}</option>
          <option value="brand">{t('groupBrand')}</option>
          <option value="category">{t('groupCategory')}</option>
        </select>
      </div>
    </div>
  );
}
