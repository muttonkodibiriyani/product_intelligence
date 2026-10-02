'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';
import type { Envelope, Schemas } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import {
  parseLaunches,
  toLaunchesQuery,
  toLaunchesSearch,
  windowEnd,
  WINDOWS,
  type LaunchesState,
} from '@/lib/launches';
import { MAX_LIMIT } from '@/lib/url-state';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { productHref } from '../explore/product-table';
import { FilterChips } from '../ui/filter-chips';
import { Known } from '../ui/known';
import { PageHeader } from '../ui/page-header';
import { Segmented } from '../ui/segmented';
import { Loading } from '../ui/skeleton';
import { useMeta, useRetailerName } from '../use-meta';
import { launchReadiness, MIN_DAYS, type LaunchReadiness, type ShopReadiness } from './readiness';

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-top';

/**
 * Products a shop started listing. Until some shop has two collection days there is nothing a
 * launch could be measured against, so the page says what it is waiting for instead of showing
 * an empty list; after that, the list for the last 30 or 7 days.
 */
export function LaunchesView() {
  const t = useTranslations('launches');
  const ts = useTranslations('state');
  const locale = useLocale();
  const meta = useMeta();
  const readiness = useMemo(() => launchReadiness(meta.data), [meta.data]);
  const shown = !!meta.data && readiness.anyReady;
  const cutoff = meta.data?.data?.cutoff;
  return (
    <section aria-labelledby="launches-title" className="space-y-6">
      <PageHeader
        id="launches-title"
        title={t('title')}
        intro={shown ? t('intro') : undefined}
        asOf={cutoff && ts('asOf', { date: formatDate(cutoff, locale) })}
      />
      {meta.isError ? (
        <ErrorNotice error={meta.error} onRetry={() => void meta.refetch()} />
      ) : !meta.data ? (
        <Loading kind="table" rows={6}>
          {t('loading')}
        </Loading>
      ) : !readiness.anyReady ? (
        <NotYet shops={readiness.shops} />
      ) : (
        <List meta={meta.data} readiness={readiness} />
      )}
    </section>
  );
}

/** The designed waiting state: the one sentence, where each shop stands, and two ways onward. */
function NotYet({ shops }: { shops: ShopReadiness[] }) {
  const t = useTranslations('launches');
  const locale = useLocale();
  return (
    <div className="panel mx-auto max-w-2xl px-6 py-10 text-center sm:px-8">
      <span
        aria-hidden="true"
        className="mx-auto mb-4 grid size-14 place-items-center rounded-card bg-surface-2 text-ink-2"
      >
        <svg
          width="26"
          height="26"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        >
          <rect x="3" y="5" width="18" height="16" rx="2" />
          <path d="M3 10h18M8 3v4M16 3v4" />
        </svg>
      </span>
      <h2 className="text-lg font-semibold tracking-tight text-balance">{t('notYet', { min: MIN_DAYS })}</h2>
      <p className="mx-auto mt-2 max-w-prose text-sm text-ink-2">{t('notYetWhy')}</p>
      {shops.length > 0 && (
        <ul aria-label={t('readiness')} className="mt-5 grid gap-2.5 text-start text-sm sm:grid-cols-2">
          {shops.map((s) => (
            <li key={s.id} className="flex items-center gap-3 rounded-ctl border border-line px-3 py-2.5">
              <span className="font-medium">{s.name}</span>
              <span className="min-w-0 flex-1 text-ink-2">
                <ShopStanding shop={s} locale={locale} />
              </span>
              <ShopDays days={s.days} />
            </li>
          ))}
        </ul>
      )}
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        <Link href={`/${locale}/promotions/`} className="btn btn-primary focus-visible:outline-2">
          {t('seePromotions')}
        </Link>
        <Link href={`/${locale}/explore/`} className="btn focus-visible:outline-2">
          {t('browseAll')}
        </Link>
      </div>
    </div>
  );
}

function ShopStanding({ shop, locale }: { shop: ShopReadiness; locale: string }) {
  const t = useTranslations('launches');
  if (shop.kind === 'imported') return t('imported', { date: formatDate(shop.date!, locale) });
  if (shop.kind === 'none' || !shop.date) return t('notCollected');
  return t('collectedDays', { n: shop.days, date: formatDate(shop.date, locale) });
}

/** One dot per day needed, the collected ones filled, and the count in words beside them. */
function ShopDays({ days }: { days: number }) {
  const t = useTranslations('launches');
  return (
    <span className="flex shrink-0 items-center gap-1 text-xs text-ink-2 tabular-nums">
      {Array.from({ length: MIN_DAYS }, (_, i) => (
        <i
          key={i}
          aria-hidden="true"
          className={`size-2 rounded-full ${i < days ? 'bg-ink' : 'bg-line-3'}`}
        />
      ))}
      <span className="ms-1">{t('ofMin', { n: Math.min(days, MIN_DAYS), min: MIN_DAYS })}</span>
    </span>
  );
}

/** The list for the chosen window, newest first; the window and any filters live in the URL. */
function List({ meta, readiness }: { meta: Envelope<Schemas['MetaView']>; readiness: LaunchReadiness }) {
  const t = useTranslations('launches');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const name = useRetailerName();
  // The window ends on the last collection day, a market date, never the cutoff's UTC date.
  const end = windowEnd(meta.data!);

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
    queryKey: ['launches', key, end],
    queryFn: ({ signal }) => api!.get('/api/v1/launches', { query: toLaunchesQuery(state, end), signal }),
    enabled: !!api,
  });
  const env = q.data;
  const data = env?.data ?? null;
  const ok = !!data && env?.status === 'ok';
  const waiting = readiness.shops.filter((s) => !s.ready);

  return (
    <>
      <FilterChips
        brand={state.brand}
        category={state.category}
        remove={(k, v) => update({ [k]: state[k].filter((x) => x !== v) })}
      />
      <section aria-labelledby="launch-items-title" className="panel">
        <header className="flex flex-wrap items-start gap-x-3 gap-y-2 px-5 pt-4">
          <div className="min-w-0 flex-1">
            <h2 id="launch-items-title" className="text-base font-semibold">
              {t('newIn', { n: state.days })}
            </h2>
            <p className="mt-0.5 text-sm text-ink-2">
              {t('newInHint')}
              {ok && (
                <>
                  {' '}
                  <span role="status" className="font-medium tabular-nums">
                    {data.truncated
                      ? t('shownOfTotal', {
                          shown: formatCount(data.items.length, locale),
                          total: formatCount(data.total, locale),
                        })
                      : t('count', { total: data.total, n: formatCount(data.total, locale) })}
                  </span>
                </>
              )}
            </p>
          </div>
          <Segmented
            label={t('window')}
            value={state.days}
            options={WINDOWS.map((n) => ({ value: n, label: t('days', { n }) }))}
            onChange={(days) => update({ days })}
          />
        </header>
        <div className="px-5 pt-3 pb-5">
          {q.isError && !env ? (
            <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
          ) : !env ? (
            <Loading kind="table" rows={6}>
              {t('loading')}
            </Loading>
          ) : (
            <>
              {env.status !== 'ok' && (
                <p role="status" className="text-sm text-ink-2">
                  {t('unavailable')}
                  {env.reason && (
                    <>
                      {' '}
                      <Known t={tr} v={env.reason} />
                    </>
                  )}
                </p>
              )}
              {ok && (
                <div id="rows">
                  <Items items={data.items} name={name} from={key} />
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
                </div>
              )}
            </>
          )}
        </div>
      </section>
      {waiting.length > 0 && (
        <p id="launch-pending" className="text-sm text-ink-2">
          {waiting.map((s, i) => (
            <span key={s.id}>
              {i > 0 && ' · '}
              {t('pending', { shop: s.name, n: Math.min(s.days, MIN_DAYS), min: MIN_DAYS })}
            </span>
          ))}
        </p>
      )}
    </>
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
  if (items.length === 0) return <p className="text-sm text-ink-2">{t('empty')}</p>;
  return (
    <div className="relative -mx-5 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${TH} text-start ps-5`}>
              {t('product')}
            </th>
            <th scope="col" className={`${TH} text-start`}>
              {t('retailer')}
            </th>
            <th scope="col" className={`${TH} pe-5 text-end`}>
              {t('firstSeen')}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={`${i.id}:${i.retailer}`} className="border-t border-line first:border-t-0">
              <th scope="row" className={`${TD} min-w-40 ps-5 text-start font-normal`}>
                <span className="flex items-center gap-3">
                  <Monogram name={i.name} />
                  <Link
                    href={productHref(locale, i.id, from, 'launches')}
                    className="font-medium text-ink hover:underline focus-visible:outline-2"
                  >
                    <span dir="auto">{i.name}</span>
                  </Link>
                </span>
              </th>
              <td className={`${TD} text-start`}>{name(i.retailer)}</td>
              <td className={`${TD} pe-5 text-end whitespace-nowrap tabular-nums`}>
                <time dateTime={i.firstSeen}>{formatDate(i.firstSeen, locale)}</time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** /launches carries no image, so the thumbnail is the name's first letter; the name sits beside it. */
function Monogram({ name }: { name: string }) {
  const first = [...name.trim()][0] ?? '';
  return (
    <span
      aria-hidden="true"
      className="grid size-10 shrink-0 place-items-center rounded-ctl bg-surface-2 text-sm font-semibold text-ink-2"
    >
      {first.toLocaleUpperCase()}
    </span>
  );
}
