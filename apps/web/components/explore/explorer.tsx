'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useId, useMemo, useState } from 'react';
import type { Envelope, Schemas } from '@/lib/api/types';
import {
  activeFilterCount,
  currentPages,
  EMPTY,
  hasPair,
  parseState,
  toQuery,
  toSearch,
  withValidSort,
  type ExploreState,
} from '@/lib/explore';
import { formatCount } from '@/lib/format';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { EnvNotes } from '../ui/env-notes';
import { useRetailerName } from '../use-meta';
import { ExportMenu } from './export-menu';
import { Filters } from './filters';
import { ProductTable } from './product-table';
import { Toolbar } from './toolbar';

type Page = Envelope<Schemas['ProductPage']>;

/** The product list. Every filter, the sort and the retailer pair live in the URL. */
export function Explorer() {
  const t = useTranslations('explore');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const name = useRetailerName();
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filtersId = useId();

  const search = sp.toString();
  const parsed = useMemo(() => parseState(new URLSearchParams(search)), [search]);
  // router.push lands a tick later; show the new state at once so a checkbox flips on click.
  // It is tied to the URL it was set on, so it drops as soon as the URL changes (or Back runs).
  const [pending, setPending] = useState<{ at: string; state: ExploreState } | null>(null);
  const state = pending?.at === search ? pending.state : parsed;
  const key = toSearch(state);
  const update = (next: Partial<ExploreState>) => {
    const target = withValidSort({ ...state, ...next });
    setPending({ at: search, state: target });
    router.push(pathname + toSearch(target), { scroll: false });
  };

  const q = useInfiniteQuery({
    queryKey: ['products', key],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api!.page('/api/v1/products', { query: toQuery(state, pageParam), signal }),
    getNextPageParam: (last) => last.body.data?.nextCursor ?? undefined,
    enabled: !!api,
  });

  const pages = q.data ? currentPages(q.data.pages) : [];
  const first = pages[0]?.body as Page | undefined;
  const last = pages[pages.length - 1]?.body as Page | undefined;
  const items = pages.flatMap((p) => p.body.data?.items ?? []);
  const total = last?.data?.total ?? 0;
  const restarted = (q.data?.pages.length ?? 0) > pages.length || pages[0]?.restarted;
  const currency = first?.meta.currency ?? '';

  const filters = (
    <Filters
      state={state}
      facets={first?.data?.facets ?? null}
      currency={currency}
      name={name}
      update={update}
    />
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <div className="lg:hidden">
        <button
          type="button"
          aria-expanded={filtersOpen}
          aria-controls={filtersId}
          onClick={() => setFiltersOpen((o) => !o)}
          className="btn focus-visible:outline-2"
        >
          {filtersOpen ? t('hideFilters') : t('showFilters', { count: activeFilterCount(state) })}
        </button>
        <div id={filtersId} hidden={!filtersOpen} className="mt-3 panel p-4">
          {filtersOpen && filters}
        </div>
      </div>
      <aside aria-label={t('filters')} className="hidden self-start panel p-4 lg:block">
        {filters}
      </aside>

      <section aria-labelledby="explore-title" className="min-w-0">
        <Toolbar key={state.q} state={state} update={update} name={name} />

        <div className="mt-4 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 id="explore-title" className="text-2xl font-bold tracking-tight">
            {t('title')}
          </h1>
          {last && (
            <p className="text-sm text-ink-2 tabular-nums" role="status">
              {t('count', { total, n: formatCount(total, locale) })}
            </p>
          )}
          {activeFilterCount(state) > 0 && (
            <button
              type="button"
              onClick={() => update(EMPTY)}
              className="text-sm text-accent underline-offset-2 hover:underline focus-visible:outline-2"
            >
              {t('clear')}
            </button>
          )}
          {last && (
            <div className="sm:ms-auto">
              {/* Keyed by the filters: a new list starts with a fresh export state. */}
              <ExportMenu key={search} state={state} total={total} n={formatCount(total, locale)} />
            </div>
          )}
        </div>

        {restarted && (
          <p role="status" className="mt-3 rounded-ctl bg-butter px-4 py-2.5 text-sm text-warn">
            {t('restarted')}
          </p>
        )}
        {first && <EnvNotes env={first} className="mt-3" />}

        <div className="mt-4">
          {q.isError && !q.data ? (
            <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
          ) : !q.data ? (
            <p role="status" aria-busy className="text-ink-2">
              {t('loading')}
            </p>
          ) : items.length === 0 ? (
            first?.status === 'ok' && (
              <div className="panel px-5 py-6">
                <p className="font-medium">{t('empty')}</p>
                <p className="mt-1 text-sm text-ink-2">{t('emptyHint')}</p>
              </div>
            )
          ) : (
            <>
              <ProductTable
                items={items}
                retailers={columns(state, first?.data?.facets.retailer ?? [])}
                pair={hasPair(state) ? (state.retailer as [string, string]) : null}
                name={name}
                from={key}
              />
              <div className="mt-4 flex flex-wrap items-center gap-4">
                <p className="text-sm text-ink-2 tabular-nums">
                  {t('showing', { shown: items.length, total })}
                </p>
                {q.hasNextPage && (
                  <button
                    type="button"
                    disabled={q.isFetchingNextPage}
                    onClick={() => void q.fetchNextPage()}
                    className="btn focus-visible:outline-2"
                  >
                    {q.isFetchingNextPage
                      ? t('loadingMore')
                      : t('more', { n: Math.min(50, Math.max(total - items.length, 1)) })}
                  </button>
                )}
              </div>
              {q.isFetchNextPageError && (
                <div className="mt-3">
                  <ErrorNotice error={q.error} onRetry={() => void q.fetchNextPage()} />
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}

/** Price columns: the picked retailers in the order picked, else every retailer with products. */
function columns(state: ExploreState, facet: Schemas['FacetCount'][]): string[] {
  if (state.retailer.length) return state.retailer;
  return facet.filter((f) => f.count > 0).map((f) => f.key);
}
