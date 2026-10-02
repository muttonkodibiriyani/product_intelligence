'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import type { Envelope, Schemas } from '@/lib/api/types';
import {
  activeFilterCount,
  currentPages,
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
import { AboutDataLink, PageHeader } from '../ui/page-header';
import { Loading } from '../ui/skeleton';
import { useRetailerName } from '../use-meta';
import { EmptyResults } from './empty-results';
import { ExportMenu } from './export-menu';
import { Filters } from './filters';
import { ProductGrid, useView, ViewToggle } from './product-grid';
import { ProductTable } from './product-table';
import { ActiveChips, Toolbar } from './toolbar';

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
  const [view, setView] = useView();

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
  const active = activeFilterCount(state);

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
    <div className="space-y-4">
      <PageHeader id="explore-title" title={t('title')} />
      <Toolbar key={state.q} state={state} update={update} name={name} />

      <div className="grid gap-6 lg:grid-cols-[12.5rem_minmax(0,1fr)]">
        <aside aria-label={t('filters')} className="hidden self-start lg:block">
          {filters}
        </aside>

        <section aria-labelledby="explore-title" className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {last && (
              <p className="text-sm font-semibold text-ink tabular-nums" role="status">
                {t('count', { total, n: formatCount(total, locale) })}
              </p>
            )}
            <ActiveChips state={state} name={name} update={update} />
            {/* Wraps on narrow screens so the row never scrolls sideways, whatever the font widths. */}
            <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2 sm:ms-auto">
              <button
                type="button"
                onClick={() => setFiltersOpen(true)}
                className="btn text-[13px] lg:hidden focus-visible:outline-2"
              >
                {t('showFilters', { count: active })}
              </button>
              <ViewToggle view={view} onChange={setView} />
              {/* Keyed by the filters: a new list starts with a fresh export state. */}
              {last && <ExportMenu key={search} state={state} total={total} n={formatCount(total, locale)} />}
            </div>
          </div>

          <Sheet open={filtersOpen} onClose={() => setFiltersOpen(false)} title={t('filters')}>
            {filters}
          </Sheet>

          <p className="mt-3 max-w-prose text-sm text-ink-2">{t('intro')}</p>
          <p className="mt-1 text-xs text-ink-2">
            <AboutDataLink />
          </p>

          {restarted && (
            <p role="status" className="mt-3 rounded-ctl bg-butter px-4 py-2.5 text-sm text-warn">
              {t('restarted')}
            </p>
          )}

          <div className="mt-4">
            {q.isError && !q.data ? (
              <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
            ) : !q.data ? (
              <Loading kind="table" rows={8}>
                {t('loading')}
              </Loading>
            ) : items.length === 0 ? (
              first && <EmptyResults env={first} />
            ) : (
              <>
                {(() => {
                  const Body = view === 'grid' ? ProductGrid : ProductTable;
                  return (
                    <Body
                      items={items}
                      retailers={columns(state, first?.data?.facets.retailer ?? [])}
                      pair={hasPair(state) ? (state.retailer as [string, string]) : null}
                      name={name}
                      from={key}
                    />
                  );
                })()}
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
    </div>
  );
}

/**
 * The filters on a phone: a native modal dialog that slides up from the bottom. Escape, the
 * backdrop and Done close it; the filters inside it only exist while it is open.
 */
function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const t = useTranslations('explore');
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal?.();
    else if (!open && d.open) d.close?.();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="m-0 mt-auto max-h-[85vh] w-full max-w-none rounded-t-2xl border-0 bg-surface p-0 text-ink shadow-pop backdrop:bg-ink/40 lg:hidden"
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <div className="flex items-center justify-between border-b border-line-2 px-4 py-3">
            <h2 id={titleId} className="text-base font-semibold">
              {title}
            </h2>
            <button type="button" onClick={onClose} className="btn text-[13px] focus-visible:outline-2">
              {t('done')}
            </button>
          </div>
          <div className="overflow-y-auto px-4 py-4">{children}</div>
        </div>
      )}
    </dialog>
  );
}

/** Price columns: the picked retailers in the order picked, else every retailer with products. */
function columns(state: ExploreState, facet: Schemas['FacetCount'][]): string[] {
  if (state.retailer.length) return state.retailer;
  return facet.filter((f) => f.count > 0).map((f) => f.key);
}
