'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useId, useMemo, useState } from 'react';
import type { Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import {
  MIN_PCTS,
  parsePromotions,
  toPromotionsQuery,
  toPromotionsSearch,
  type MinPct,
  type PromotionsState,
} from '@/lib/promotions';
import { MAX_LIMIT } from '@/lib/url-state';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { productHref } from '../explore/product-table';
import { Card } from '../ui/card';
import { EnvNotes } from '../ui/env-notes';
import { FilterChips } from '../ui/filter-chips';
import { Known } from '../ui/known';
import { Money } from '../ui/money';
import { RetailerChecks } from '../ui/retailer-checks';
import { PageHeader } from '../ui/page-header';
import { Loading } from '../ui/skeleton';
import { useRetailerName } from '../use-meta';

const TH = 'th';
const TD = 'px-3 py-2.5 align-top';

/** Products below their regular price on the latest day, deepest first, and each retailer's share. */
export function PromotionsView() {
  const t = useTranslations('promotions');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const name = useRetailerName();
  const minId = useId();

  const search = sp.toString();
  const parsed = useMemo(() => parsePromotions(new URLSearchParams(search)), [search]);
  const [pending, setPending] = useState<{ at: string; state: PromotionsState } | null>(null);
  const state = pending?.at === search ? pending.state : parsed;
  const key = toPromotionsSearch(state);
  const update = (next: Partial<PromotionsState>) => {
    const target = { ...state, ...next };
    setPending({ at: search, state: target });
    router.push(pathname + toPromotionsSearch(target), { scroll: false });
  };

  const q = useQuery({
    queryKey: ['promotions', key],
    queryFn: ({ signal }) => api!.get('/api/v1/promotions', { query: toPromotionsQuery(state), signal }),
    enabled: !!api,
  });
  const env = q.data;
  const data = env?.data ?? null;

  return (
    <section aria-labelledby="promotions-title" className="space-y-6">
      <PageHeader id="promotions-title" title={t('title')} intro={t('intro')} />

      <div className="flex flex-wrap items-start gap-x-8 gap-y-3 panel px-5 py-4">
        <RetailerChecks value={state.retailer} onChange={(retailer) => update({ retailer })} />
        <div className="flex flex-col gap-1">
          <label htmlFor={minId} className="text-xs font-medium text-ink-2">
            {t('minPct')}
          </label>
          <select
            id={minId}
            value={state.minPct}
            onChange={(e) => update({ minPct: e.target.value as MinPct })}
            className="field focus-visible:outline-2"
          >
            {MIN_PCTS.map((v) => (
              <option key={v} value={v}>
                {v ? t('atLeast', { pct: v }) : t('anyDiscount')}
              </option>
            ))}
          </select>
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
          <EnvNotes env={env} />
          {data && (
            <>
              <Shares retailers={data.retailers} name={name} />
              <section aria-labelledby="promo-items-title" id="rows">
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <h2 id="promo-items-title" className="text-base font-semibold">
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
            </>
          )}
        </>
      )}
    </section>
  );
}

/** Each retailer's share of priced products on promotion; one without data says why. */
function Shares({
  retailers,
  name,
}: {
  retailers: Schemas['RetailerPromo'][];
  name: (id: string) => string;
}) {
  const t = useTranslations('promotions');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  return (
    <Card id="shares" title={t('shares')} flush>
      <div className="relative overflow-x-auto px-2">
        <table className="w-full text-sm">
          <thead className="border-b border-line">
            <tr>
              <th scope="col" className={`${TH} text-start`}>
                {t('retailer')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('priced')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('onPromo')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('share')}
              </th>
            </tr>
          </thead>
          <tbody>
            {retailers.map((r) => (
              <tr key={r.retailer} className="border-t border-line first:border-t-0">
                <th scope="row" className={`${TD} min-w-28 text-start font-normal`}>
                  {name(r.retailer)}
                </th>
                {r.share === null ? (
                  <td colSpan={3} className={`${TD} min-w-48 text-ink-2`}>
                    {r.reason ? <Known t={tr} v={r.reason} /> : t('noShare')}
                  </td>
                ) : (
                  <>
                    <td className={`${TD} text-end tabular-nums`}>{formatCount(r.n, locale)}</td>
                    <td className={`${TD} text-end tabular-nums`}>{formatCount(r.onPromo, locale)}</td>
                    <td className={`${TD} text-end`}>
                      <bdi className="tabular-nums" dir="ltr">{`${r.share}%`}</bdi>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="px-5 pt-1 pb-2 text-xs text-ink-2">{t('sharesHint')}</p>
    </Card>
  );
}

function Items({
  items,
  name,
  from,
}: {
  items: Schemas['PromoItem'][];
  name: (id: string) => string;
  from: string;
}) {
  const t = useTranslations('promotions');
  const locale = useLocale();
  if (items.length === 0) return <p className="panel px-4 py-3 text-sm text-ink-2">{t('empty')}</p>;
  return (
    <div className="relative overflow-x-auto panel">
      <table className="w-full text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${TH} text-start whitespace-nowrap`}>
              {t('product')}
            </th>
            <th scope="col" className={`${TH} text-end whitespace-nowrap`}>
              {t('depth')}
            </th>
            <th scope="col" className={`${TH} text-end whitespace-nowrap`}>
              {t('price')}
            </th>
            <th scope="col" className={`${TH} text-end whitespace-nowrap`}>
              {t('regular')}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={`${i.id}:${i.retailer}`} className="border-t border-line first:border-t-0">
              <th scope="row" className={`${TD} min-w-44 text-start font-normal`}>
                <Link
                  href={productHref(locale, i.id, from, 'promotions')}
                  className="text-accent hover:underline focus-visible:outline-2"
                >
                  <span dir="auto">{i.name}</span>
                </Link>
                <span className="block text-xs text-ink-2">{name(i.retailer)}</span>
              </th>
              <td className={`${TD} text-end font-medium`}>
                <bdi className="tabular-nums whitespace-nowrap" dir="ltr">{`−${i.depthPct}%`}</bdi>
              </td>
              <td className={`${TD} text-end`}>
                <Money m={i.price} locale={locale} />
              </td>
              <td className={`${TD} text-end text-ink-2`}>
                <Money m={i.regular} locale={locale} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
