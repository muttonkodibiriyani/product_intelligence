'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useId, useMemo, useState } from 'react';
import type { Schemas } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import {
  MIN_PCTS,
  listedItems,
  notMeasured,
  parsePromotions,
  pickedShop,
  toPromotionsExportQuery,
  toPromotionsQuery,
  toPromotionsSearch,
  type MinPct,
  type PromotionsState,
} from '@/lib/promotions';
import { MAX_LIMIT } from '@/lib/url-state';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { ExportMenu } from '../explore/export-menu';
import { useView, ViewToggle } from '../explore/product-grid';
import { monogram, RowThumb } from '../explore/row-thumb';
import { productHref } from '../explore/product-table';
import { Card } from '../ui/card';
import { FilterChips } from '../ui/filter-chips';
import { Reason } from '../ui/known';
import { Price } from '../ui/money';
import { PageHeader } from '../ui/page-header';
import { ProductCard, type PriceLine } from '../ui/product-card';
import { RetailerDot } from '../ui/retailer-dot';
import { Loading } from '../ui/skeleton';
import { useRetailerName } from '../use-meta';
import { ShopTiles } from './shop-tiles';

type Item = Schemas['PromoItem'];

/**
 * Promotions, products first: one tile per shop (its share on promotion, or the one line saying
 * its discounts are not measured), then the discounted products as the Products card with now,
 * was and −%, deepest first. The minimum discount, Grid/List and Export sit in the panel's
 * header. Every filter lives in the URL. When nothing on screen is measured (the capability is
 * off, the picked shop's was-prices are unverified) the card says so with the API's reason, never
 * "no product is discounted": withheld data reads as not measured, never as 0 or none.
 */
export function PromotionsView() {
  const t = useTranslations('promotions');
  const ts = useTranslations('state');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const name = useRetailerName();
  const minId = useId();
  const [view, setView] = useView();

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
  const listed = data ? listedItems(data) : null;
  const items = listed?.items ?? [];
  const shop = pickedShop(state);
  const why = env ? notMeasured(env, shop) : null;
  const total = listed?.total ?? null;
  const n = formatCount(total ?? 0, locale);
  const title = shop ? t('itemsAt', { shop: name(shop) }) : t('items');
  const asOf = env && ts('asOf', { date: formatDate(env.meta.cutoff, locale) });

  return (
    <section aria-labelledby="promotions-title" className="space-y-5">
      <PageHeader id="promotions-title" title={t('title')} intro={t('intro')} asOf={asOf} />

      {q.isError && !env ? (
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      ) : !env ? (
        <Loading kind="table" rows={6}>
          {t('loading')}
        </Loading>
      ) : (
        <>
          {data && <ShopTiles retailers={data.retailers} items={items} name={name} />}

          <Card
            id="rows"
            title={title}
            question={why ? undefined : t('itemsHint')}
            meta={
              why ? undefined : (
                <span role="status">
                  {total === null
                    ? t('shownOnly', { shown: formatCount(items.length, locale) })
                    : data?.truncated
                      ? t('shownOfTotal', { shown: formatCount(items.length, locale), total: n })
                      : t('count', { total, n })}
                </span>
              )
            }
            tools={
              why ? undefined : (
                <>
                  <div className="flex items-center gap-2">
                    <label htmlFor={minId} className="text-[13px] text-ink-2">
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
                  <ViewToggle view={view} onChange={setView} />
                  {/* Keyed by the filters: a new list starts with a fresh export state. */}
                  <ExportMenu
                    key={search}
                    path="/api/v1/export/promotions"
                    query={(format) => toPromotionsExportQuery(state, format)}
                    fallback="pi-promotions"
                    total={data?.total ?? 0}
                    n={formatCount(data?.total ?? 0, locale)}
                  />
                </>
              )
            }
          >
            <FilterChips
              retailer={state.retailer}
              brand={state.brand}
              category={state.category}
              name={name}
              remove={(k, v) => update({ [k]: state[k].filter((x) => x !== v) })}
              removeRetailer={(v) => update({ retailer: state.retailer.filter((x) => x !== v) })}
            />
            <div className={state.retailer.length + state.brand.length + state.category.length ? 'mt-3' : ''}>
              {why ? (
                <p className="text-sm">
                  <span className="font-medium text-ink">
                    {shop ? t('notMeasuredAt', { shop: name(shop) }) : t('notMeasuredFilters')}
                  </span>{' '}
                  <span className="text-ink-2">
                    <Reason v={why} />
                  </span>
                </p>
              ) : items.length === 0 ? (
                <p className="rounded-ctl bg-surface-2 px-4 py-3 text-sm text-ink-2">{t('empty')}</p>
              ) : view === 'grid' ? (
                <Grid items={items} name={name} from={key} />
              ) : (
                <List items={items} name={name} from={key} />
              )}
            </div>
            {!why && data?.truncated && (
              <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
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
          </Card>
        </>
      )}
    </section>
  );
}

/** A promotion as the card's one price line: the price now and the regular price struck through. */
function promoLine(i: Item, label: string): PriceLine {
  return { retailer: i.retailer, label, price: i.price, was: i.regular, saved: i.saved ?? null };
}

/** One click from Promotions to the product's source evidence section. */
function evidenceHref(locale: string, id: string, from: string): string {
  return `${productHref(locale, id, from, 'promotions')}#evidence`;
}

type Rows = {
  items: readonly Item[];
  name: (id: string) => string;
  from: string;
};

/**
 * The discounted products as image-first cards (`ProductCard`), ranked deepest first. New API 1.17
 * visual fields are read defensively: an older response simply keeps the placeholder and omits the
 * brand, category and saved amount rather than inventing them.
 */
function Grid({ items, name, from }: Rows) {
  const t = useTranslations('promotions');
  const tc = useTranslations('productCard');
  const locale = useLocale();
  return (
    <ol aria-label={t('results')} className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
      {items.map((i, index) => (
        <li key={`${i.id}:${i.retailer}`} className="relative min-w-0">
          <span
            aria-label={t('rankLabel', { rank: index + 1 })}
            className="absolute top-2 end-2 z-[2] rounded-full bg-surface px-2 py-1 text-[11px] font-semibold text-ink shadow-sm"
          >
            <bdi dir="ltr">#{formatCount(index + 1, locale)}</bdi>
          </span>
          <ProductCard
            href={evidenceHref(locale, i.id, from)}
            image={i.image ?? null}
            imageRetailer={i.retailer}
            brand={i.brand || null}
            name={i.name}
            category={i.category || null}
            lines={[promoLine(i, name(i.retailer))]}
            chip={{ tone: 'good', label: <bdi dir="ltr">{tc('off', { pct: i.depthPct })}</bdi> }}
          />
        </li>
      ))}
    </ol>
  );
}

/** The dense view: product and shop, then the depth, the price now and the regular price. */
function List({ items, name, from }: Rows) {
  const t = useTranslations('promotions');
  const tc = useTranslations('productCard');
  const locale = useLocale();
  const th = 'th whitespace-nowrap';
  const td = 'px-3 py-2.5 align-top';
  return (
    <div className="relative overflow-x-auto rounded-ctl border border-line-2">
      <table className="w-full text-sm">
        <caption className="sr-only">{t('results')}</caption>
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${th} text-start`}>
              {t('rank')}
            </th>
            <th scope="col" className={`${th} text-start`}>
              {t('product')}
            </th>
            <th scope="col" className={`${th} text-end`}>
              {t('depth')}
            </th>
            <th scope="col" className={`${th} text-end`}>
              {t('saved')}
            </th>
            <th scope="col" className={`${th} text-end`}>
              {t('price')}
            </th>
            <th scope="col" className={`${th} text-end`}>
              {t('regular')}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((i, idx) => (
            <tr
              key={`${i.id}:${i.retailer}`}
              className="border-t border-line-2 first:border-t-0 hover:bg-surface-2"
            >
              <td className={`${td} text-start font-semibold text-ink-2`}>
                <bdi dir="ltr">#{formatCount(idx + 1, locale)}</bdi>
              </td>
              <th scope="row" className={`${td} min-w-44 text-start font-normal`}>
                <div className="flex min-w-56 items-start gap-3">
                  <RowThumb
                    url={i.image ?? null}
                    label={tc('noImage')}
                    monogram={i.brand ? monogram(i.brand) : undefined}
                    retailer={i.retailer}
                    cls="size-14 shrink-0 rounded-ctl bg-surface-2 p-1"
                    px={56}
                  />
                  <span className="min-w-0">
                    {i.brand && (
                      <span
                        className="block truncate text-[11px] tracking-[0.06em] text-ink-3 uppercase"
                        dir="auto"
                      >
                        {i.brand}
                      </span>
                    )}
                    <Link
                      href={evidenceHref(locale, i.id, from)}
                      className="font-medium text-ink hover:underline focus-visible:outline-2"
                    >
                      <span dir="auto">{i.name}</span>
                    </Link>
                    {i.category && (
                      <span className="block truncate text-xs text-ink-3" dir="auto">
                        {i.category}
                      </span>
                    )}
                    <span className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-2">
                      <RetailerDot id={i.retailer} index={idx} />
                      {name(i.retailer)}
                    </span>
                  </span>
                </div>
              </th>
              <td className={`${td} text-end`}>
                <span className="verdict verdict-good">
                  <bdi dir="ltr">{`−${i.depthPct}%`}</bdi>
                </span>
              </td>
              <td className={`${td} text-end font-medium tabular-nums`}>
                {i.saved ? (
                  <Price of={{ price: i.saved }} locale={locale} />
                ) : (
                  <span className="font-normal text-ink-3">{t('withheld')}</span>
                )}
              </td>
              <td className={`${td} text-end font-medium tabular-nums`}>
                <Price of={i} locale={locale} />
              </td>
              <td className={`${td} text-end text-ink-3 tabular-nums`}>
                <s>
                  <Price of={{ price: i.regular }} locale={locale} />
                </s>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
