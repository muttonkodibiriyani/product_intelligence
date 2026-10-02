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
import { formatCount, formatDate } from '@/lib/format';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { FilterChips } from '../ui/filter-chips';
import { PageHeader } from '../ui/page-header';
import { Loading } from '../ui/skeleton';
import { useMeta, useRetailerName } from '../use-meta';
import { activeRetailers } from '../widgets/model';
import { useCategoryCompare } from '../widgets/use-category';
import { CompareEmpty } from './compare-empty';
import { CompareRows, ShownOfTotal } from './compare-rows';
import { About, Coverage, Groups, Verdict } from './compare-summary';
import { ExportMatched } from './export-matched';
import { PairPicker } from './pair-picker';

/**
 * Two shops' prices on the same products: the answer first (who is cheaper on how many), the
 * matched products as evidence, everything that couldn't be compared folded away with its
 * reason, and an honest empty state while nothing is matched yet. The pair, grouping and filters
 * live in the URL; with exactly two collected shops the pair is implied.
 */
export function CompareView() {
  const t = useTranslations('compare');
  const ts = useTranslations('state');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const name = useRetailerName();
  const meta = useMeta();
  const active = useMemo(() => activeRetailers(meta.data?.data), [meta.data]);

  const search = sp.toString();
  const parsed = useMemo(() => parseCompare(new URLSearchParams(search)), [search]);
  // As in the explorer: show a picked value at once, until the URL catches up.
  const [pending, setPending] = useState<{ at: string; state: CompareState } | null>(null);
  const picked = pending?.at === search ? pending.state : parsed;
  // The dataset's only pair needs no picking.
  const fixed =
    active.length === 2 &&
    (!hasComparePair(picked) || (active.includes(picked.base) && active.includes(picked.other)));
  const state: CompareState =
    fixed && !hasComparePair(picked) ? { ...picked, base: active[0]!, other: active[1]! } : picked;
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
  const summary = data?.summary && data.summary.n > 0 ? data.summary : null;
  // The category medians exist before any product is matched; only the empty state shows them.
  const category = useCategoryCompare(
    ready && env && !summary ? { base: state.base, other: state.other } : null,
  );

  return (
    <section aria-labelledby="compare-title" className="space-y-5">
      <PageHeader
        id="compare-title"
        title={t('title')}
        intro={t('intro')}
        asOf={env && ts('asOf', { date: formatDate(env.meta.cutoff, locale) })}
        tools={summary && <ExportMatched state={state} />}
      />

      <PairPicker state={state} update={update} fixed={fixed} />

      <FilterChips
        brand={state.brand}
        category={state.category}
        remove={(k, v) => update({ [k]: state[k].filter((x) => x !== v) })}
      />

      {!ready ? (
        meta.data || meta.isError ? (
          <div className="panel px-5 py-6">
            <p className="font-medium">{t('pickPair')}</p>
            <p className="mt-1 text-sm text-ink-2">{t('pickPairHint')}</p>
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
      ) : !summary || !data ? (
        <CompareEmpty
          env={env}
          data={data}
          pair={{ base: state.base, other: state.other }}
          name={name}
          category={category}
        />
      ) : (
        <>
          <Verdict data={{ ...data, summary }} name={name} />
          <section aria-labelledby="matched-title" id="matched">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <h2 id="matched-title" className="text-base font-semibold">
                {t('matched.title', { n: formatCount(summary.n, locale), count: summary.n })}
              </h2>
              {data.truncated && <ShownOfTotal shown={data.rows.length} total={data.total} />}
            </div>
            <p className="mt-1 text-sm text-ink-2">{t('matched.hint')}</p>
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
          {data.groupBy && data.groups.length > 0 && (
            <Groups
              data={data}
              name={name}
              onPick={(k) => update({ [data.groupBy!]: [k], limit: LIMITS[0] })}
            />
          )}
          <div className="grid gap-5 lg:grid-cols-2">
            <Coverage data={data} name={name} />
            <About cohort={env.cohort ?? null} />
          </div>
        </>
      )}
    </section>
  );
}
