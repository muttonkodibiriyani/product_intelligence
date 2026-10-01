'use client';

import { useQuery } from '@tanstack/react-query';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';
import {
  hasComparePair,
  LIMITS,
  parseCompare,
  toCompareQuery,
  toCompareSearch,
  type CompareState,
} from '@/lib/compare';
import { formatCount } from '@/lib/format';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { EnvNotes } from '../ui/env-notes';
import { FilterChips } from '../ui/filter-chips';
import { useRetailerName } from '../use-meta';
import { CompareRows } from './compare-rows';
import { Groups, Sides, Summary } from './compare-summary';
import { PairPicker } from './pair-picker';

/** Two retailers' prices on the same products. The pair, grouping and filters live in the URL. */
export function CompareView() {
  const t = useTranslations('compare');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const name = useRetailerName();

  const search = sp.toString();
  const parsed = useMemo(() => parseCompare(new URLSearchParams(search)), [search]);
  // As in the explorer: show a picked value at once, until the URL catches up.
  const [pending, setPending] = useState<{ at: string; state: CompareState } | null>(null);
  const state = pending?.at === search ? pending.state : parsed;
  const key = toCompareSearch(state);
  const update = (next: Partial<CompareState>) => {
    const target = { ...state, ...next };
    setPending({ at: search, state: target });
    router.push(pathname + toCompareSearch(target), { scroll: false });
  };
  const ready = hasComparePair(state);

  const q = useQuery({
    queryKey: ['compare', key],
    queryFn: ({ signal }) => api!.get('/api/v1/compare', { query: toCompareQuery(state), signal }),
    enabled: !!api && ready,
  });
  const env = q.data;
  const data = env?.data ?? null;

  return (
    <section aria-labelledby="compare-title" className="space-y-6">
      <div>
        <h1 id="compare-title" className="text-2xl font-bold tracking-tight">
          {t('title')}
        </h1>
        <p className="mt-1 max-w-prose text-sm text-ink-2">{t('intro')}</p>
      </div>

      <PairPicker state={state} update={update} />

      <FilterChips
        brand={state.brand}
        category={state.category}
        remove={(k, v) => update({ [k]: state[k].filter((x) => x !== v) })}
      />

      {!ready ? (
        <div className="panel px-5 py-6">
          <p className="font-medium">{t('pickPair')}</p>
          <p className="mt-1 text-sm text-ink-2">{t('pickPairHint')}</p>
        </div>
      ) : q.isError && !env ? (
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      ) : !env ? (
        <p role="status" aria-busy className="text-ink-2">
          {t('loading')}
        </p>
      ) : (
        <>
          <EnvNotes env={env} />
          {data && (
            <>
              <Summary data={data} cohort={env.cohort ?? null} name={name} />
              <Sides data={data} name={name} />
              {data.groupBy && data.groups.length > 0 && (
                <Groups
                  data={data}
                  name={name}
                  onPick={(k) => update({ [data.groupBy!]: [k], limit: LIMITS[0] })}
                />
              )}
              <section aria-labelledby="rows-title" id="rows">
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <h2 id="rows-title" className="text-base font-semibold">
                    {t('rows')}
                  </h2>
                  <p role="status" className="text-sm text-ink-2 tabular-nums">
                    {data.truncated
                      ? t('shownOfTotal', {
                          shown: formatCount(data.rows.length, locale),
                          total: formatCount(data.total, locale),
                        })
                      : t('count', { total: data.total, n: formatCount(data.total, locale) })}
                  </p>
                </div>
                <p className="mt-1 text-sm text-ink-2">{t('rowsHint')}</p>
                <div className="mt-3">
                  <CompareRows data={data} name={name} from={key} />
                </div>
                {data.truncated && (
                  <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
                    <p className="text-ink-2">{t('truncated')}</p>
                    {state.limit < LIMITS[LIMITS.length - 1]! ? (
                      <button
                        type="button"
                        onClick={() => update({ limit: LIMITS[LIMITS.length - 1]! })}
                        className="btn focus-visible:outline-2"
                      >
                        {t('showMore', { n: formatCount(LIMITS[LIMITS.length - 1]!, locale) })}
                      </button>
                    ) : (
                      <p className="text-ink-2">{t('narrow')}</p>
                    )}
                  </div>
                )}
              </section>
            </>
          )}
        </>
      )}
    </section>
  );
}
