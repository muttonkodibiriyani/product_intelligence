'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useId, useMemo, useState } from 'react';
import type { Schemas } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import {
  cleanDay,
  parseLaunches,
  toLaunchesQuery,
  toLaunchesSearch,
  type LaunchesState,
} from '@/lib/launches';
import { MAX_LIMIT } from '@/lib/url-state';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { productHref } from '../explore/product-table';
import { FilterChips } from '../ui/filter-chips';
import { RetailerChecks } from '../ui/retailer-checks';
import { PageHeader } from '../ui/page-header';
import { Loading } from '../ui/skeleton';
import { useRetailerName } from '../use-meta';

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-top';

/** Products a retailer started listing, newest first. */
export function LaunchesView() {
  const t = useTranslations('launches');
  const ts = useTranslations('state');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const name = useRetailerName();
  const sinceId = useId();

  const search = sp.toString();
  const parsed = useMemo(() => parseLaunches(new URLSearchParams(search)), [search]);
  const [pending, setPending] = useState<{ at: string; state: LaunchesState } | null>(null);
  const state = pending?.at === search ? pending.state : parsed;
  const key = toLaunchesSearch(state);
  const update = (next: Partial<LaunchesState>) => {
    const target = { ...state, ...next };
    setPending({ at: search, state: target });
    router.push(pathname + toLaunchesSearch(target), { scroll: false });
  };

  const q = useQuery({
    queryKey: ['launches', key],
    queryFn: ({ signal }) => api!.get('/api/v1/launches', { query: toLaunchesQuery(state), signal }),
    enabled: !!api,
  });
  const env = q.data;
  const data = env?.data ?? null;

  return (
    <section aria-labelledby="launches-title" className="space-y-6">
      <PageHeader
        id="launches-title"
        title={t('title')}
        intro={t('intro')}
        asOf={env && ts('asOf', { date: formatDate(env.meta.cutoff, locale) })}
      />

      <div className="flex flex-wrap items-start gap-x-8 gap-y-3 panel px-5 py-4">
        <RetailerChecks value={state.retailer} onChange={(retailer) => update({ retailer })} />
        <div className="flex flex-col gap-1">
          <label htmlFor={sinceId} className="text-xs font-medium text-ink-2">
            {t('since')}
          </label>
          <div className="flex items-center gap-2">
            <input
              id={sinceId}
              type="date"
              value={state.since}
              onChange={(e) => {
                const since = cleanDay(e.target.value);
                if (since !== state.since) update({ since });
              }}
              className="field focus-visible:outline-2"
            />
            {state.since && (
              <button
                type="button"
                onClick={() => update({ since: '' })}
                className="text-sm text-accent underline-offset-2 hover:underline focus-visible:outline-2"
              >
                {t('anyDay')}
              </button>
            )}
          </div>
        </div>
      </div>

      <FilterChips
        brand={state.brand}
        category={state.category}
        remove={(k, v) => update({ [k]: state[k].filter((x) => x !== v) })}
      />

      {q.isError && !env ? (
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      ) : !env ? (
        <Loading kind="table" rows={6}>
          {t('loading')}
        </Loading>
      ) : (
        <>
          {/* A catalogue the view does not apply to: one line, no empty table. */}
          {env.status !== 'ok' && (
            <p role="status" className="text-sm text-ink-2">
              {t('unavailable')}
            </p>
          )}
          {data && env.status === 'ok' && (
            <section aria-labelledby="launch-items-title" id="rows">
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <h2 id="launch-items-title" className="text-base font-semibold">
                  {t('items')}
                </h2>
                <p role="status" className="text-sm text-ink-2 tabular-nums">
                  {data.truncated
                    ? t('shownOfTotal', {
                        shown: formatCount(data.items.length, locale),
                        total: formatCount(data.total, locale),
                      })
                    : t('count', { total: data.total, n: formatCount(data.total, locale) })}
                </p>
              </div>
              <p className="mt-1 text-sm text-ink-2">{t('itemsHint')}</p>
              <div className="mt-3">
                <Items items={data.items} name={name} from={key} />
              </div>
              {data.truncated && (
                <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
                  <p className="text-ink-2">{t('truncated')}</p>
                  {state.limit < MAX_LIMIT ? (
                    <button
                      type="button"
                      onClick={() => update({ limit: MAX_LIMIT })}
                      className="btn focus-visible:outline-2"
                    >
                      {t('showMore', { n: formatCount(MAX_LIMIT, locale) })}
                    </button>
                  ) : (
                    <p className="text-ink-2">{t('narrow')}</p>
                  )}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </section>
  );
}

function Items({
  items,
  name,
  from,
}: {
  items: Schemas['Launch'][];
  name: (id: string) => string;
  from: string;
}) {
  const t = useTranslations('launches');
  const locale = useLocale();
  if (items.length === 0) return <p className="panel px-4 py-3 text-sm text-ink-2">{t('empty')}</p>;
  return (
    <div className="relative overflow-x-auto panel">
      <table className="w-full text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${TH} text-start`}>
              {t('product')}
            </th>
            <th scope="col" className={`${TH} text-start`}>
              {t('retailer')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {t('firstSeen')}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={`${i.id}:${i.retailer}`} className="border-t border-line first:border-t-0">
              <th scope="row" className={`${TD} min-w-40 text-start font-normal`}>
                <Link
                  href={productHref(locale, i.id, from, 'launches')}
                  className="text-accent hover:underline focus-visible:outline-2"
                >
                  <span dir="auto">{i.name}</span>
                </Link>
              </th>
              <td className={`${TD} text-start`}>{name(i.retailer)}</td>
              <td className={`${TD} text-end whitespace-nowrap tabular-nums`}>
                <time dateTime={i.firstSeen}>{formatDate(i.firstSeen, locale)}</time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
