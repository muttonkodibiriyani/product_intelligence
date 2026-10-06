'use client';

import { useTranslations } from 'next-intl';
import { useId, type ReactNode } from 'react';
import { pick, type CompareState, type GroupBy } from '@/lib/compare';
import { retailerName } from '@/lib/retailers';
import { useMeta } from '../use-meta';
import { retailerTone } from './model';

const SELECT = 'min-w-0 field py-1.5 font-semibold focus-visible:outline-2 disabled:opacity-60';

/** A retailer's coloured mark, the one the tally bar and the headline use for it. */
export function RetailerDot({ id, side }: { id: string; side: 0 | 1 }) {
  return (
    <span
      aria-hidden
      className="inline-block size-2.5 shrink-0 rounded-full align-middle"
      style={{ background: retailerTone(id, side) }}
    />
  );
}

/**
 * "Ulta against Sephora": the pair as one sentence, each shop a select. With exactly two collected
 * shops there is nothing to pick, so the sentence is plain text. The grouping sits at the end.
 */
export function PairPicker({
  state,
  update,
  fixed,
  tools,
  grouping = true,
}: {
  state: CompareState;
  update: (next: Partial<CompareState>) => void;
  /** The only pair the dataset has: shown, not picked. */
  fixed: boolean;
  tools?: ReactNode;
  /** The "Group by" picker; a page that does not group (Insights) leaves it out. */
  grouping?: boolean;
}) {
  const t = useTranslations('compare');
  const retailers = useMeta().data?.data?.retailers ?? [];
  const id = useId();
  const nameOf = (rid: string) => retailers.find((r) => r.id === rid)?.name ?? rid;
  const option = (r: (typeof retailers)[number]) => (
    <option key={r.id} value={r.id}>
      {retailerName(r.id, r.name)}
    </option>
  );
  const side = (s: 'base' | 'other', i: 0 | 1) => (
    <span className="inline-flex min-w-0 items-center gap-2">
      {state[s] && <RetailerDot id={state[s]} side={i} />}
      {fixed ? (
        <b className="font-semibold">{nameOf(state[s])}</b>
      ) : (
        <>
          <label htmlFor={`${id}-${s}`} className="sr-only">
            {t(s === 'base' ? 'pickBase' : 'pickOther')}
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
        </>
      )}
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 panel px-5 py-3">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
        {side('base', 0)}
        <span className="text-ink-2">{t('against')}</span>
        {side('other', 1)}
      </p>
      <button
        type="button"
        onClick={() => update({ base: state.other, other: state.base })}
        disabled={!state.base && !state.other}
        aria-label={t('swap')}
        title={t('swap')}
        className="btn px-2 py-1.5 focus-visible:outline-2"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          aria-hidden
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M7 16V4m0 0L3 8m4-4 4 4M17 8v12m0 0 4-4m-4 4-4-4" />
        </svg>
      </button>
      <div className="flex min-w-0 flex-wrap items-center gap-2 sm:ms-auto">
        {grouping && (
          <>
            <label htmlFor={`${id}-group`} className="text-xs font-medium text-ink-2">
              {t('groupBy')}
            </label>
            <select
              id={`${id}-group`}
              value={state.groupBy ?? ''}
              onChange={(e) => update({ groupBy: (e.target.value || null) as GroupBy | null })}
              className="min-w-0 field py-1.5 focus-visible:outline-2"
            >
              <option value="">{t('groupNone')}</option>
              <option value="brand">{t('groupBrand')}</option>
              <option value="category">{t('groupCategory')}</option>
            </select>
          </>
        )}
        {tools}
      </div>
    </div>
  );
}
