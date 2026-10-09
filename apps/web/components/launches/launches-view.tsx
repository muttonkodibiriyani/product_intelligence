'use client';

import { keepPreviousData, useQueries, useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState, type ReactNode } from 'react';
import type { Envelope, Schemas } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import {
  filterLaunchEvidence,
  launchEvidenceRow,
  type EvidenceField,
  type FieldState,
  type LaunchEvidenceRow,
} from '@/lib/launch-evidence';
import {
  launchesQueryKey,
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
import { monogram, RowThumb } from '../explore/row-thumb';
import { productHref } from '../explore/product-table';
import { FilterChips } from '../ui/filter-chips';
import { FreshnessStrip, useSourceFreshness } from '../ui/freshness';
import { Known } from '../ui/known';
import { Money } from '../ui/money';
import { PageHeader } from '../ui/page-header';
import { Segmented } from '../ui/segmented';
import { Loading } from '../ui/skeleton';
import { useMeta, useRetailerName } from '../use-meta';
import { LaunchesFilters } from './launches-filters';
import { launchReadiness, MIN_DAYS, type LaunchReadiness, type ShopReadiness } from './readiness';

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-top';
/** Filters typed into a field: each keystroke replaces the history entry instead of adding one. */
const TYPED: readonly string[] = [
  'dateFrom',
  'dateTo',
  'priceMin',
  'priceMax',
  'discountMin',
  'size',
  'color',
  'shade',
];

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
      <p className="mx-auto mt-2 max-w-prose text-sm text-ink-2">{t('firstObservedWhy')}</p>
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
  const from = toLaunchesSearch(state);
  const update = (next: Partial<LaunchesState>) => {
    const target = { ...state, ...next };
    setPending({ at: search, state: target });
    const typed = Object.keys(next).every((k) => TYPED.includes(k));
    router[typed ? 'replace' : 'push'](pathname + toLaunchesSearch(target), { scroll: false });
  };

  const q = useQuery({
    queryKey: launchesQueryKey(state, end),
    queryFn: ({ signal }) => api!.get('/api/v1/launches', { query: toLaunchesQuery(state, end), signal }),
    enabled: !!api,
    placeholderData: keepPreviousData,
  });
  const env = q.data;
  const data = env?.data ?? null;
  const ok = !!data && env?.status === 'ok';
  const waiting = readiness.shops.filter((s) => !s.ready);
  const items = ok ? data.items : [];
  const detailIds = [...new Set(items.map((item) => item.id))];
  const details = useQueries({
    queries: detailIds.map((id) => ({
      queryKey: ['product', id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api!.get('/api/v1/products/{product_id}', { params: { product_id: id }, signal }),
      enabled: !!api,
    })),
  });
  const detailById = new Map(
    detailIds.map((id, index) => {
      const detail = details[index];
      return [id, detail?.isPending ? undefined : (detail?.data ?? null)] as const;
    }),
  );
  const evidenceRows = items.map((item) => launchEvidenceRow(item, detailById.get(item.id), env?.caveats));
  const filteredRows = filterLaunchEvidence(evidenceRows, state);
  const evidenceLoading = details.some((detail) => detail.isPending);
  const evidenceErrors = details.filter((detail) => detail.isError).length;
  const sources = useSourceFreshness(env?.caveats);

  return (
    <>
      <FilterChips
        retailer={state.retailer}
        brand={state.brand}
        category={state.category}
        name={name}
        remove={(k, v) => update({ [k]: state[k].filter((x) => x !== v) })}
        removeRetailer={(v) => update({ retailer: state.retailer.filter((x) => x !== v) })}
      />
      {ok && (
        <LaunchesFilters
          state={state}
          rows={evidenceRows}
          retailers={meta.data!.retailers.filter((retailer) =>
            readiness.shops.some((shop) => shop.id === retailer.id),
          )}
          currency={env.meta.currency}
          end={end}
          update={update}
        />
      )}
      <FreshnessStrip sources={sources} name={name} only={readiness.shops.map((shop) => shop.id)} />
      <section aria-labelledby="launch-items-title" className="panel">
        <header className="flex flex-wrap items-start gap-x-3 gap-y-2 px-5 pt-4">
          <div className="min-w-0 flex-1">
            <h2 id="launch-items-title" className="text-base font-semibold">
              {t('firstObservedIn', { n: state.days })}
            </h2>
            <p className="mt-0.5 text-sm text-ink-2">
              {t('firstObservedHint')}
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
                  {!evidenceLoading && filteredRows.length !== data.items.length && (
                    <span className="ms-2 text-ink-2">
                      {t('filteredCount', { n: formatCount(filteredRows.length, locale) })}
                    </span>
                  )}
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
                  {evidenceLoading && (
                    <p role="status" className="mb-3 text-sm text-ink-2">
                      {t('loadingEvidence')}
                    </p>
                  )}
                  {evidenceErrors > 0 && (
                    <p role="status" className="mb-3 text-sm text-warn">
                      {t('evidenceUnavailable', { n: evidenceErrors })}
                    </p>
                  )}
                  <Items items={filteredRows} name={name} from={from} />
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
  items: LaunchEvidenceRow[];
  name: (id: string) => string;
  from: string;
}) {
  const t = useTranslations('launches');
  if (items.length === 0) return <p className="text-sm text-ink-2">{t('empty')}</p>;
  return (
    <>
      <ul className="grid gap-3 md:hidden">
        {items.map((row) => (
          <li key={`${row.launch.id}:${row.launch.retailer}`} className="rounded-ctl border border-line p-3">
            <Product row={row} from={from} />
            <dl className="mt-3 grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-3 gap-y-2 text-[13px]">
              <Term label={t('retailer')}>{name(row.launch.retailer)}</Term>
              <RowFields row={row} />
            </dl>
          </li>
        ))}
      </ul>
      <div className="relative -mx-5 hidden overflow-x-auto md:block">
        <table className="w-full min-w-[1120px] text-sm">
          <thead className="border-b border-line">
            <tr>
              <th scope="col" className={`${TH} text-start ps-5`}>
                {t('product')}
              </th>
              <th scope="col" className={`${TH} text-start`}>
                {t('retailer')}
              </th>
              <th scope="col" className={`${TH} text-start`}>
                {t('variant')}
              </th>
              <th scope="col" className={`${TH} text-start`}>
                {t('pricing')}
              </th>
              <th scope="col" className={`${TH} text-start`}>
                {t('availability')}
              </th>
              <th scope="col" className={`${TH} pe-5 text-start`}>
                {t('evidence')}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr
                key={`${row.launch.id}:${row.launch.retailer}`}
                className="border-t border-line first:border-t-0"
              >
                <th scope="row" className={`${TD} min-w-64 ps-5 text-start font-normal`}>
                  <Product row={row} from={from} />
                </th>
                <td className={`${TD} min-w-32 text-start`}>{name(row.launch.retailer)}</td>
                <td className={`${TD} min-w-48`}>
                  <dl className="grid gap-1.5">
                    <Term label={t('sku')}>
                      <Field field={row.sku} />
                    </Term>
                    <Term label={t('size')}>
                      <SizeField field={row.size} />
                    </Term>
                    <Term label={t('color')}>
                      <Field field={row.color} />
                    </Term>
                    <Term label={t('shade')}>
                      <Field field={row.shade} />
                    </Term>
                  </dl>
                </td>
                <td className={`${TD} min-w-52`}>
                  <dl className="grid gap-1.5">
                    <Term label={t('currentPrice')}>
                      <MoneyField field={row.currentPrice} />
                    </Term>
                    <Term label={t('regularPrice')}>
                      <MoneyField field={row.regularPrice} />
                    </Term>
                    <Term label={t('memberPrice')}>
                      <MoneyField field={row.memberPrice} />
                    </Term>
                    <Term label={t('promotion')}>
                      <PromotionField field={row.promotionPct} />
                    </Term>
                  </dl>
                </td>
                <td className={`${TD} min-w-40`}>
                  <AvailabilityField field={row.availability} />
                </td>
                <td className={`${TD} min-w-64 pe-5`}>
                  <Evidence row={row} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Product({ row, from }: { row: LaunchEvidenceRow; from: string }) {
  const t = useTranslations('launches');
  const locale = useLocale();
  return (
    <div className="flex min-w-0 items-start gap-3">
      <RowThumb
        url={row.image.value}
        retailer={row.launch.retailer}
        label={t('noImage')}
        monogram={row.brand.value ? monogram(row.brand.value) : undefined}
      />
      <span className="min-w-0">
        <Field field={row.brand} className="block text-[11px] tracking-[0.06em] text-ink-3 uppercase" />
        <Link
          href={productHref(locale, row.launch.id, from, 'launches')}
          className="block font-medium text-ink hover:underline focus-visible:outline-2"
        >
          <span dir="auto">{row.launch.name}</span>
        </Link>
        <span className="mt-0.5 block text-xs text-ink-3">
          {t('productId')}: <bdi>{row.launch.id}</bdi>
        </span>
        <span className="mt-0.5 block text-xs text-ink-3">
          {t('category')}: <CategoryField field={row.category} />
        </span>
        <span className="mt-0.5 block text-xs text-ink-3">
          {t('image')}: <State state={row.image.state} observed={t('available')} />
        </span>
      </span>
    </div>
  );
}

function RowFields({ row }: { row: LaunchEvidenceRow }) {
  const t = useTranslations('launches');
  return (
    <>
      <Term label={t('sku')}>
        <Field field={row.sku} />
      </Term>
      <Term label={t('size')}>
        <SizeField field={row.size} />
      </Term>
      <Term label={t('color')}>
        <Field field={row.color} />
      </Term>
      <Term label={t('shade')}>
        <Field field={row.shade} />
      </Term>
      <Term label={t('currentPrice')}>
        <MoneyField field={row.currentPrice} />
      </Term>
      <Term label={t('regularPrice')}>
        <MoneyField field={row.regularPrice} />
      </Term>
      <Term label={t('memberPrice')}>
        <MoneyField field={row.memberPrice} />
      </Term>
      <Term label={t('promotion')}>
        <PromotionField field={row.promotionPct} />
      </Term>
      <Term label={t('availability')}>
        <AvailabilityField field={row.availability} />
      </Term>
      <Term label={t('evidence')}>
        <Evidence row={row} />
      </Term>
    </>
  );
}

function Term({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function Field({ field, className }: { field: EvidenceField<string>; className?: string }) {
  if (field.state !== 'observed' || field.value === null)
    return <State state={field.state} className={className} />;
  return (
    <span className={className} dir="auto">
      {field.value}
    </span>
  );
}

function CategoryField({ field }: { field: EvidenceField<string[]> }) {
  if (field.state !== 'observed' || field.value === null) return <State state={field.state} />;
  return <span dir="auto">{field.value.join(' / ')}</span>;
}

function SizeField({ field }: { field: LaunchEvidenceRow['size'] }) {
  if (field.state !== 'observed' || field.value === null) return <State state={field.state} />;
  if (typeof field.value === 'string') return <bdi>{field.value}</bdi>;
  return (
    <bdi dir="ltr" className="tabular-nums">
      {field.value.value} {field.value.unit}
    </bdi>
  );
}

function MoneyField({ field }: { field: LaunchEvidenceRow['currentPrice'] }) {
  const locale = useLocale();
  if (field.state !== 'observed' || field.value === null) return <State state={field.state} />;
  return <Money m={field.value} locale={locale} />;
}

function PromotionField({ field }: { field: LaunchEvidenceRow['promotionPct'] }) {
  if (field.state !== 'observed' || field.value === null) return <State state={field.state} />;
  return (
    <bdi dir="ltr" className="verdict verdict-good">
      −{field.value}%
    </bdi>
  );
}

function AvailabilityField({ field }: { field: LaunchEvidenceRow['availability'] }) {
  const t = useTranslations('launches.filters.availabilityStates');
  if (field.state !== 'observed' || field.value === null) return <State state={field.state} />;
  return <span>{t(field.value)}</span>;
}

function Evidence({ row }: { row: LaunchEvidenceRow }) {
  const t = useTranslations('launches');
  const locale = useLocale();
  const source = row.source.value ? safeHttpUrl(row.source.value) : null;
  return (
    <div className="space-y-1.5 text-xs">
      <p>
        <span className="text-ink-3">{t('retailerDeclaration')}: </span>
        <State state={row.retailerDeclaration.state} />
      </p>
      <p>
        <span className="text-ink-3">{t('firstObserved')}: </span>
        <time dateTime={row.launch.firstSeen}>{formatDate(row.launch.firstSeen, locale)}</time>
        <span className="ms-1 text-ink-3">({t('notLaunchDate')})</span>
      </p>
      <p>
        <span className="text-ink-3">{t('evidenceDate')}: </span>
        {row.evidenceAt.value ? (
          <time dateTime={row.evidenceAt.value}>{formatDate(row.evidenceAt.value, locale, true)}</time>
        ) : (
          <State state={row.evidenceAt.state} />
        )}
      </p>
      {row.staleAsOf && (
        <p className="text-warn">{t('staleAsOf', { date: formatDate(row.staleAsOf, locale) })}</p>
      )}
      <p>
        <span className="text-ink-3">{t('source')}: </span>
        {source ? (
          <a
            href={source}
            target="_blank"
            rel="noopener noreferrer nofollow"
            referrerPolicy="no-referrer"
            className="text-accent hover:underline focus-visible:outline-2"
          >
            {t('openSource')}
          </a>
        ) : row.source.value ? (
          <State state="invalid" />
        ) : (
          <State state={row.source.state} />
        )}
      </p>
      <ul aria-label={t('evidenceStates')} className="flex flex-wrap gap-1">
        {row.states.map((state) => (
          <li key={state} className="pill">
            {t(`filters.evidenceStates.${state}`)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function State({ state, observed, className }: { state: FieldState; observed?: string; className?: string }) {
  const t = useTranslations('launches.fieldStates');
  return (
    <span
      className={`${state === 'invalid' || state === 'contradictory' ? 'text-warn' : 'text-ink-3'} ${className ?? ''}`}
    >
      {state === 'observed' && observed ? observed : t(state)}
    </span>
  );
}

function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}
