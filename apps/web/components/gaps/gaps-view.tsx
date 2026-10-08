'use client';

import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useId, useMemo, useState } from 'react';
import type { ApiClient, ExportPath } from '@/lib/api/client';
import type { Envelope } from '@/lib/api/types';
import {
  type BrandGaps,
  type BrandRow,
  type GapItems,
  type GapsState,
  ITEMS_PAGE,
  type Side,
  SORTS,
  type Sort,
  gapsServed,
  notAtOf,
  notAtShops,
  parseGaps,
  sortBrands,
  toGapsQuery,
  toGapsSearch,
  toItemsQuery,
} from '@/lib/brand-gaps';
import { formatCount, formatDate } from '@/lib/format';
import { displayBrand } from '@/lib/insights';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { ExportMenu } from '../explore/export-menu';
import { productHref } from '../explore/product-table';
import { Card, CardGrid } from '../ui/card';
import { Known } from '../ui/known';
import { PageHeader } from '../ui/page-header';
import { RetailerDot } from '../ui/retailer-dot';
import { Segmented } from '../ui/segmented';
import { Loading } from '../ui/skeleton';
import { pct } from '../widgets/model';
import { useMeta, useRetailerName } from '../use-meta';

// DRAFT: /brand-gaps is not in the openapi yet (lib/brand-gaps.ts). Once schema.gen.ts has the
// routes, these become typed `api.get` / `api.page` calls and the casts go.
type DraftGet = <T>(path: string, opts: { query: object; signal?: AbortSignal }) => Promise<Envelope<T>>;
const draftGet = (api: ApiClient) => api.get as unknown as DraftGet;
const EXPORT_PATH = '/api/v1/export/brand-gaps' as ExportPath;

type Open = (list: GapsState['list']) => void;

/**
 * Brand gaps: what one shop (Ulta by default) lists, brand by brand, against the other shops.
 * The headline is the unmatched count with its own label (unmatched is not proven absent); beside
 * it, the per-shop counts that are proven (`notAt`) and the shops that are not counted at all,
 * with why. Every count opens the listings it was counted from, and the open list exports as
 * CSV or JSONL. A withheld shop never reads as 0. Every choice lives in the URL.
 */
export function GapsView() {
  const t = useTranslations('gaps');
  const ts = useTranslations('state');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const name = useRetailerName();
  const meta = useMeta();
  const served = gapsServed(meta.data);
  const focusId = useId();

  const search = sp.toString();
  const parsed = useMemo(() => parseGaps(new URLSearchParams(search)), [search]);
  const [pending, setPending] = useState<{ at: string; state: GapsState } | null>(null);
  const state = pending?.at === search ? pending.state : parsed;
  const update = (next: Partial<GapsState>) => {
    const target = { ...state, ...next };
    setPending({ at: search, state: target });
    router.push(pathname + toGapsSearch(target), { scroll: false });
  };
  const open: Open = (list) => update({ list });

  const query = toGapsQuery(state);
  const q = useQuery({
    queryKey: ['brand-gaps', query],
    queryFn: ({ signal }) => draftGet(api!)<BrandGaps>('/api/v1/brand-gaps', { query, signal }),
    enabled: !!api && served === true,
  });
  const env = q.data;
  const g = env?.data ?? null;
  const shop = name(state.focus);
  const asOf = env && ts('asOf', { date: formatDate(env.meta.cutoff, locale) });
  const shops = g ? [g.focus, ...g.others] : [state.focus];

  const tools = (
    <>
      <div className="flex items-center gap-2">
        <label htmlFor={focusId} className="text-[13px] text-ink-2">
          {t('shop')}
        </label>
        <select
          id={focusId}
          value={state.focus}
          onChange={(e) => update({ focus: e.target.value, list: null })}
          className="field focus-visible:outline-2"
        >
          {shops.map((r) => (
            <option key={r} value={r}>
              {name(r)}
            </option>
          ))}
        </select>
      </div>
      <Segmented<Sort>
        label={t('sort.label')}
        value={state.sort}
        options={SORTS.map((s) => ({ value: s, label: t(`sort.${s}`) }))}
        onChange={(sort) => update({ sort })}
      />
    </>
  );

  return (
    <section aria-labelledby="gaps-title" className="space-y-5">
      <PageHeader id="gaps-title" title={t('title')} intro={t('intro', { shop })} asOf={asOf} tools={tools} />

      {served === false ? (
        <p role="note" className="rounded-ctl bg-surface-2 px-4 py-3 text-sm text-ink-2">
          {t('notServed')}
        </p>
      ) : q.isError && !env ? (
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      ) : !env ? (
        <Loading kind="table" rows={6}>
          {t('loading')}
        </Loading>
      ) : !g ? (
        <p role="note" className="rounded-ctl bg-surface-2 px-4 py-3 text-sm text-ink-2">
          <Known t={tr} v={env.reason ?? 'not_applicable'} />
        </p>
      ) : (
        <>
          <Overview g={g} state={state} open={open} />
          {state.list && (
            <Items key={toGapsSearch({ ...state, sort: 'focus_only' })} g={g} state={state} open={open} />
          )}
          <BrandTable g={g} state={state} open={open} />
        </>
      )}
    </section>
  );
}

/** The side's label: focus_only reads as the API labels it (unmatched or missing). */
function useSideLabel(g: BrandGaps) {
  const t = useTranslations('gaps');
  const name = useRetailerName();
  return (side: Side, retailer: string | null) =>
    side === 'focus_only'
      ? t(`label.${g.focusOnlyLabel}`)
      : side === 'not_at'
        ? t('side.not_at', { shop: name(retailer ?? '') })
        : t(`side.${side}`);
}

/** A count that opens its list. Pressed while its list is open. */
function Count({
  n,
  list,
  state,
  open,
  label,
  className = '',
}: {
  n: number;
  list: NonNullable<GapsState['list']>;
  state: GapsState;
  open: Open;
  label: string;
  className?: string;
}) {
  const locale = useLocale();
  const pressed =
    state.list?.side === list.side &&
    state.list.brand === list.brand &&
    (state.list.retailer ?? null) === (list.retailer ?? null);
  if (n === 0)
    return <span className={`tabular-nums text-ink-2 ${className}`}>{formatCount(0, locale)}</span>;
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={label}
      onClick={() => open(pressed ? null : list)}
      className={`rounded-[6px] px-1 tabular-nums underline decoration-line underline-offset-4 hover:decoration-ink focus-visible:outline-2 ${
        pressed ? 'bg-surface-2 font-semibold' : ''
      } ${className}`}
    >
      {formatCount(n, locale)}
    </button>
  );
}

function Overview({ g, state, open }: { g: BrandGaps; state: GapsState; open: Open }) {
  const t = useTranslations('gaps');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const side = useSideLabel(g);
  const all = t('allBrands');
  const tot = g.totals;
  const shop = name(g.focus);
  const proven = notAtShops(g);

  return (
    <CardGrid>
      <Card
        id="gap-headline"
        span={4}
        title={t(`label.${g.focusOnlyLabel}`)}
        question={t(`labelNote.${g.focusOnlyLabel}`)}
      >
        <p className="flex items-baseline gap-2">
          <Count
            n={tot.focusOnly}
            list={{ brand: null, side: 'focus_only', retailer: null }}
            state={state}
            open={open}
            label={t('count', { side: side('focus_only', null), brand: all, n: tot.focusOnly })}
            className="text-[28px] leading-8 font-semibold"
          />
          {tot.focusOnlyShare !== null && (
            <span className="text-sm text-ink-2">{pct(tot.focusOnlyShare, locale)}</span>
          )}
        </p>
        <p className="mt-1 text-sm text-ink-2">
          {t('ofListings', { n: formatCount(tot.focusN, locale), shop })}
        </p>
        <dl className="mt-4 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
          {(['both', 'unconfirmed', 'family'] as const).map((s) => (
            <div key={s} className="contents">
              <dt className="text-ink-2">{side(s, null)}</dt>
              <dd className="text-end">
                <Count
                  n={tot[s]}
                  list={{ brand: null, side: s, retailer: null }}
                  state={state}
                  open={open}
                  label={t('count', { side: side(s, null), brand: all, n: tot[s] })}
                />
              </dd>
            </div>
          ))}
          <dt className="text-ink-2">{side('others_only', null)}</dt>
          <dd className="text-end">
            {tot.othersOnly === null ? (
              <span className="text-ink-2" title={t('othersOnlyWithheld', { shop })}>
                –<span className="sr-only">{t('othersOnlyWithheld', { shop })}</span>
              </span>
            ) : (
              <Count
                n={tot.othersOnly}
                list={{ brand: null, side: 'others_only', retailer: null }}
                state={state}
                open={open}
                label={t('count', { side: side('others_only', null), brand: all, n: tot.othersOnly })}
              />
            )}
          </dd>
        </dl>
      </Card>

      <Card id="gap-not-at" span={4} title={t('notAt.title')} question={t('notAt.note')}>
        {proven.length === 0 ? (
          <p className="text-sm text-ink-2">{t('notAt.none')}</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {tot.notAt.map((c, i) => (
              <li key={c.retailer} className="flex items-center gap-2">
                <RetailerDot id={c.retailer} index={i + 1} />
                <span className="flex-1">{name(c.retailer)}</span>
                <Count
                  n={c.n}
                  list={{ brand: null, side: 'not_at', retailer: c.retailer }}
                  state={state}
                  open={open}
                  label={t('count', { side: side('not_at', c.retailer), brand: all, n: c.n })}
                />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        id="gap-withheld"
        span={4}
        title={t('withheld.title')}
        question={g.withheld.length ? t('withheld.note') : undefined}
      >
        {g.withheld.length === 0 ? (
          <p className="text-sm text-ink-2">–</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {g.withheld.map((w) => (
              <li key={w.retailer}>
                <span className="font-medium">{name(w.retailer)}</span>{' '}
                <span className="text-ink-2">
                  <Known t={tr} v={w.reason} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </CardGrid>
  );
}

function BrandTable({ g, state, open }: { g: BrandGaps; state: GapsState; open: Open }) {
  const t = useTranslations('gaps');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const side = useSideLabel(g);
  const shop = name(g.focus);
  const proven = notAtShops(g);
  const rows = sortBrands(g.byBrand, state.sort, locale);
  const th = 'th whitespace-nowrap text-end';

  if (rows.length === 0)
    return <p className="rounded-ctl bg-surface-2 px-4 py-3 text-sm text-ink-2">{t('empty', { shop })}</p>;

  const cell = (r: BrandRow, s: Side, n: number, retailer: string | null = null) => (
    <Count
      n={n}
      list={{ brand: r.brand, side: s, retailer }}
      state={state}
      open={open}
      label={t('count', { side: side(s, retailer), brand: displayBrand(r.brand), n })}
    />
  );

  return (
    <div className="relative overflow-x-auto panel">
      <table className="w-full text-sm">
        <caption className="sr-only">{t('title')}</caption>
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className="th sticky start-0 bg-surface text-start">
              {t('col.brand')}
            </th>
            <th scope="col" className={th}>
              {t('col.listings', { shop })}
            </th>
            <th scope="col" className={th}>
              {t('col.both')}
            </th>
            <th scope="col" className={th}>
              {t('col.unconfirmed')}
            </th>
            <th scope="col" className={th}>
              {t('col.family')}
            </th>
            <th scope="col" className={th}>
              {t(`label.${g.focusOnlyLabel}`)}
            </th>
            <th scope="col" className={th}>
              {t('col.share')}
            </th>
            {proven.map((r) => (
              <th key={r} scope="col" className={th}>
                {t('col.notAt', { shop: name(r) })}
              </th>
            ))}
            <th scope="col" className={th}>
              {t('col.othersOnly')}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.brand} className="border-b border-line last:border-0">
              <th scope="row" className="sticky start-0 bg-surface px-3 py-2 text-start font-medium">
                {displayBrand(r.brand)}
              </th>
              <td className="px-3 py-2 text-end tabular-nums">{formatCount(r.focusN, locale)}</td>
              <td className="px-3 py-2 text-end">{cell(r, 'both', r.both)}</td>
              <td className="px-3 py-2 text-end">{cell(r, 'unconfirmed', r.unconfirmed)}</td>
              <td className="px-3 py-2 text-end">{cell(r, 'family', r.family)}</td>
              <td className="px-3 py-2 text-end font-semibold">{cell(r, 'focus_only', r.focusOnly)}</td>
              <td className="px-3 py-2 text-end text-ink-2 tabular-nums">
                {r.focusOnlyShare !== null ? (
                  pct(r.focusOnlyShare, locale)
                ) : (
                  <span title={r.shareReason ? tr(r.shareReason) : undefined}>
                    –<span className="sr-only">{r.shareReason && <Known t={tr} v={r.shareReason} />}</span>
                  </span>
                )}
              </td>
              {proven.map((x) => {
                const n = notAtOf(r, x);
                return (
                  <td key={x} className="px-3 py-2 text-end">
                    {n === null ? <span className="text-ink-2">–</span> : cell(r, 'not_at', n, x)}
                  </td>
                );
              })}
              <td className="px-3 py-2 text-end">
                {r.othersOnly === null ? (
                  <span className="text-ink-2" title={t('othersOnlyWithheld', { shop })}>
                    –
                  </span>
                ) : (
                  cell(r, 'others_only', r.othersOnly)
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Items({ g, state, open }: { g: BrandGaps; state: GapsState; open: Open }) {
  const t = useTranslations('gaps');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const side = useSideLabel(g);
  const { api } = useAuth();
  const list = state.list!;
  const query = toItemsQuery(state)!;

  const q = useInfiniteQuery({
    queryKey: ['brand-gaps-items', query],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      draftGet(api!)<GapItems>('/api/v1/brand-gaps/items', {
        query: { ...query, limit: ITEMS_PAGE, ...(pageParam ? { cursor: pageParam } : {}) },
        signal,
      }),
    getNextPageParam: (last) => last.data?.nextCursor ?? null,
    enabled: !!api,
  });
  const first = q.data?.pages[0];
  const items = q.data?.pages.flatMap((p) => p.data?.items ?? []) ?? [];
  const total = first?.data?.total ?? 0;
  const brand = list.brand ? displayBrand(list.brand) : t('allBrands');
  const title = t('list.title', { side: side(list.side, list.retailer), brand });

  return (
    <Card
      id="gap-list"
      title={title}
      meta={first?.data ? <span role="status">{t('list.total', { n: total })}</span> : undefined}
      state={q.isPending ? 'loading' : q.isError && !first ? 'error' : 'ready'}
      reason={
        q.isError && !first ? <ErrorNotice error={q.error} onRetry={() => void q.refetch()} /> : undefined
      }
      flush
      skeleton="table"
      tools={
        <>
          {first?.data && total > 0 && (
            <ExportMenu
              path={EXPORT_PATH}
              query={(format) => ({ ...query, format }) as never}
              fallback={t('exportFile')}
              total={total}
              n={formatCount(total, locale)}
            />
          )}
          <button
            type="button"
            onClick={() => open(null)}
            className="btn py-1.5 text-sm focus-visible:outline-2"
          >
            {t('list.close')}
          </button>
        </>
      }
    >
      {first && !first.data ? (
        <p role="note" className="mx-5 rounded-ctl bg-surface-2 px-4 py-3 text-sm">
          <span className="font-medium">{name(list.retailer ?? g.focus)}</span>{' '}
          <span className="text-ink-2">
            <Known t={tr} v={first.reason ?? 'not_applicable'} />
          </span>
        </p>
      ) : items.length === 0 ? (
        <p className="mx-5 rounded-ctl bg-surface-2 px-4 py-3 text-sm text-ink-2">{t('list.empty')}</p>
      ) : (
        <>
          <ul className="divide-y divide-line border-t border-line">
            {items.map((it) => (
              <li
                key={`${it.retailer}:${it.id}`}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-5 py-2 text-sm"
              >
                <span className="min-w-0 flex-1 basis-64">
                  <Link
                    href={productHref(locale, it.id)}
                    className="font-medium underline-offset-2 hover:underline focus-visible:outline-2"
                  >
                    {it.name}
                  </Link>
                  <span className="block text-xs text-ink-2">
                    {displayBrand(it.brand)}
                    {it.category.length > 0 && ` · ${it.category.join(' › ')}`}
                  </span>
                </span>
                <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
                  <RetailerDot id={it.retailer} />
                  {name(it.retailer)}
                </span>
                {it.bothAt.length > 0 && (
                  <span className="text-xs text-ink-2">
                    {t('list.alsoAt', { shops: it.bothAt.map(name).join(', ') })}
                  </span>
                )}
                {it.notAt.length > 0 && (
                  <span className="text-xs text-ink-2">
                    {t('list.notAt', { shops: it.notAt.map(name).join(', ') })}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {q.hasNextPage && (
            <div className="px-5 pt-3">
              <button
                type="button"
                disabled={q.isFetchingNextPage}
                onClick={() => void q.fetchNextPage()}
                className="btn py-1.5 text-sm focus-visible:outline-2"
              >
                {t('list.more')}
              </button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
