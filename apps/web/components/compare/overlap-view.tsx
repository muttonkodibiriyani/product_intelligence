'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { useId } from 'react';
import type { Envelope, Schemas } from '@/lib/api/types';
import { toOverlapQuery, type CompareState } from '@/lib/compare';
import { formatCount, formatDate } from '@/lib/format';
import { navHref } from '@/lib/nav';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { DatedShopNotice } from '../ui/dated-shop-notice';
import { FilterChips } from '../ui/filter-chips';
import { Known } from '../ui/known';
import { PageHeader } from '../ui/page-header';
import { Loading } from '../ui/skeleton';
import { useRetailerName } from '../use-meta';
import { CompareViews } from './compare-views';
import { overlapOptions, overlapRows, type Option } from './model';
import { OverlapRows } from './overlap-rows';
import { PairPicker } from './pair-picker';
import { useCompareState } from './use-compare-state';

type Comparison = Schemas['Comparison'];

/**
 * Every product sold at both shops, reviewed or not: both prices and the gap, biggest gap first,
 * with how each pair was matched on hover or focus. Unreviewed pairs are labelled; the Summary
 * view keeps counting confirmed pairs only. Brand and category narrow the list in the API, and
 * their options are tallied from the whole pair, so picking one never empties the other's menu.
 */
export function OverlapView() {
  const t = useTranslations('overlap');
  const tc = useTranslations('compare');
  const ts = useTranslations('state');
  const locale = useLocale();
  const { api } = useAuth();
  const name = useRetailerName();
  const { state, update, fixed, ready, key, meta } = useCompareState();
  const filtered = state.brand.length + state.category.length > 0;

  const ask = (s: Pick<CompareState, 'base' | 'other' | 'brand' | 'category'>) => ({
    queryKey: ['compare', 'overlap', s.base, s.other, s.brand, s.category],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      api!.get('/api/v1/compare', { query: toOverlapQuery(s), signal }),
    enabled: !!api && ready,
  });
  const q = useQuery(ask(state));
  // Unfiltered, the same request as the list itself, so it costs nothing extra.
  const all = useQuery(ask({ ...state, brand: [], category: [] }));
  const options = overlapOptions(all.data?.data?.rows ?? []);

  const env = q.data;
  const data = env?.data ?? null;
  const rows = overlapRows(data?.rows ?? []);

  return (
    <section aria-labelledby="overlap-title" className="space-y-5">
      <PageHeader
        id="overlap-title"
        title={t('title')}
        intro={t('intro')}
        asOf={env && ts('asOf', { date: formatDate(env.meta.cutoff, locale) })}
      />

      <CompareViews current="overlap" search={key} />

      <DatedShopNotice shops={ready ? [state.base, state.other] : []} />

      <PairPicker
        state={state}
        update={update}
        fixed={fixed}
        grouping={false}
        tools={
          <>
            <Pick
              label={t('brand')}
              value={state.brand}
              options={options.brand}
              onPick={(v) => update({ brand: v ? [v] : [] })}
            />
            <Pick
              label={t('category')}
              value={state.category}
              options={options.category}
              onPick={(v) => update({ category: v ? [v] : [] })}
            />
          </>
        }
      />

      <FilterChips
        brand={state.brand}
        category={state.category}
        remove={(k, v) => update({ [k]: state[k].filter((x) => x !== v) })}
      />

      {!ready ? (
        meta.data || meta.isError ? (
          <div className="panel px-5 py-6">
            <p className="font-medium">{tc('pickPair')}</p>
            <p className="mt-1 text-sm text-ink-2">{tc('pickPairHint')}</p>
          </div>
        ) : (
          <Loading kind="table" rows={6}>
            {t('loading')}
          </Loading>
        )
      ) : q.isError && !env ? (
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      ) : !env ? (
        <Loading kind="table" rows={6}>
          {t('loading')}
        </Loading>
      ) : !data || rows.length === 0 ? (
        <OverlapEmpty
          env={env}
          names={{ base: name(state.base), other: name(state.other) }}
          filtered={filtered}
          clear={() => update({ brand: [], category: [] })}
        />
      ) : (
        <section aria-labelledby="overlap-count" className="space-y-3">
          <div>
            <h2 id="overlap-count" className="text-base font-semibold">
              {t('count', { n: formatCount(data.total, locale), count: data.total })}
            </h2>
            {data.truncated ? (
              <p role="status" className="mt-1 text-sm text-ink-2">
                {t('shown', {
                  shown: formatCount(rows.length, locale),
                  total: formatCount(data.total, locale),
                })}
              </p>
            ) : (
              <p className="mt-1 text-sm text-ink-2 tabular-nums">
                {t('split', {
                  reviewed: formatCount(rows.filter((r) => r.counted).length, locale),
                  unreviewed: formatCount(rows.filter((r) => !r.counted).length, locale),
                })}
              </p>
            )}
            <p className="mt-1 text-sm text-ink-2">{t('hint')}</p>
          </div>
          <OverlapRows rows={rows} data={data} name={name} from={key} />
        </section>
      )}
    </section>
  );
}

/** A single-choice menu over the pair's brands or categories, each with its product count. */
function Pick({
  label,
  value,
  options,
  onPick,
}: {
  label: string;
  value: readonly string[];
  options: readonly Option[];
  onPick: (v: string) => void;
}) {
  const t = useTranslations('overlap');
  const locale = useLocale();
  const id = useId();
  const current = value.length === 1 ? value[0]! : '';
  // A value from the URL that the tally doesn't hold (a typo, or past the first 500 rows) still shows.
  const list =
    current && !options.some((o) => o.key === current) ? [{ key: current, n: 0 }, ...options] : options;
  return (
    <>
      <label htmlFor={id} className="text-xs font-medium text-ink-2">
        {label}
      </label>
      <select
        id={id}
        value={current}
        onChange={(e) => onPick(e.target.value)}
        className="min-w-0 max-w-48 field py-1.5 focus-visible:outline-2"
      >
        <option value="">{t('all')}</option>
        {list.map((o) => (
          <option key={o.key} value={o.key}>
            {o.n > 0 ? `${o.key} (${formatCount(o.n, locale)})` : o.key}
          </option>
        ))}
      </select>
    </>
  );
}

/**
 * Nothing to list: the data not being available says so with the API's reason; a filter that
 * matches nothing offers to clear it; a pair with no match yet points to the by-category prices.
 */
function OverlapEmpty({
  env,
  names,
  filtered,
  clear,
}: {
  env: Envelope<Comparison | null>;
  names: { base: string; other: string };
  filtered: boolean;
  clear: () => void;
}) {
  const t = useTranslations('overlap');
  const ts = useTranslations('state');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  if (env.status !== 'ok')
    return (
      <div role="status" className="panel px-5 py-6">
        <p className="font-medium">{ts('notAvailable')}</p>
        {env.reason && (
          <p className="mt-1 text-sm text-ink-2">
            <Known t={tr} v={env.reason} />
          </p>
        )}
      </div>
    );
  if (filtered)
    return (
      <div className="panel px-5 py-6">
        <p className="font-medium">{t('emptyFiltered')}</p>
        <button type="button" onClick={clear} className="btn mt-4 text-sm focus-visible:outline-2">
          {t('clear')}
        </button>
      </div>
    );
  return (
    <div className="panel px-5 py-6">
      <p className="font-medium">{t('empty', names)}</p>
      <p className="mt-1 max-w-prose text-sm text-ink-2">{t('emptyHint')}</p>
      <Link href={navHref('prices', locale)} className="btn mt-4 text-sm focus-visible:outline-2">
        {t('emptyLink')}
      </Link>
    </div>
  );
}
