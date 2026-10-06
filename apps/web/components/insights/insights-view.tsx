'use client';

import { useQueries, useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, type ReactNode } from 'react';
import { ApiError } from '@/lib/api/client';
import { EMPTY, toQuery } from '@/lib/explore';
import { formatCount, formatDate } from '@/lib/format';
import {
  INSIGHTS_API,
  insightsServed,
  notCollected,
  pickedShop,
  shopPairs,
  STOCK_BRANDS_SHOWN,
  type Insights,
  type Stockouts,
} from '@/lib/insights';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { Known } from '../ui/known';
import { PageHeader } from '../ui/page-header';
import { RetailerDot, retailerColor } from '../ui/retailer-dot';
import { Loading } from '../ui/skeleton';
import { useMeta, useRetailerName } from '../use-meta';
import { activeRetailers, compareHref, exploreHref } from '../widgets/model';
import { Ideas } from './ideas';
import { PairPrices } from './pair-cards';
import { cols, LINK, Num, linkTag, boldTag, Heading, Info, ShopHead, Panel, Label, Off } from './parts';

/**
 * Insights: what the latest crawl of each shop shows, at a glance and in plain words, one column
 * per shop and never ranked (task 01a102f2). The shop selector narrows the page to one shop
 * (`?shop=`). Every number opens the Products (Explore) list it counts; the method behind a
 * number is in its (i) tooltip, not on the page. Cross-shop prices count reviewed exact matches
 * only, per pair, and are never summed across pairs. Stock-outs are counts, never percentages;
 * whole brands the source reports unavailable are named as such and kept out of the headline.
 */
export function InsightsView() {
  const t = useTranslations('insights');
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const meta = useMeta();
  const active = useMemo(() => activeRetailers(meta.data?.data), [meta.data]);
  const shop = pickedShop(sp, active);
  const shops = shop ? [shop] : active;

  // An API older than INSIGHTS_API has no /insights: say so, and ask it nothing.
  const served = insightsServed(meta.data);
  const pairs = useMemo(() => shopPairs(active), [active]);
  // /insights is per pair: its pricing is the pair's, its stock, size and value rows cover every
  // shop, so the first pair's answer serves the per-shop sections.
  const queries = useQueries({
    queries: pairs.map(({ base, other }) => ({
      queryKey: ['insights', `${base},${other}`],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api!.get('/api/v1/insights', { query: { retailers: `${base},${other}` }, signal }),
      enabled: !!api && served === true,
    })),
  });
  const first = queries[0];
  const data = first?.data?.data;
  // A 404 from /insights means the route is not deployed whatever /meta says: the same honest
  // "not available yet", never an error card.
  const missing = first?.error instanceof ApiError && first.error.status === 404;

  const pick = (next: string | null) => {
    const p = new URLSearchParams(sp.toString());
    if (next) p.set('shop', next);
    else p.delete('shop');
    const q = p.toString();
    router.push(pathname + (q ? `?${q}` : ''), { scroll: false });
  };

  return (
    <section aria-labelledby="insights-title" className="space-y-7">
      <PageHeader
        id="insights-title"
        title={t('title')}
        intro={t('intro')}
        tools={active.length >= 2 ? <ShopPicker shops={active} value={shop} onChange={pick} /> : undefined}
      />
      {served === false ? (
        <div role="note" className="panel px-5 py-6 text-sm text-ink-2">
          {t('unavailable', { need: INSIGHTS_API, have: meta.data!.meta.apiVersion })}
        </div>
      ) : served === undefined ? (
        meta.isError ? (
          <ErrorNotice error={meta.error} onRetry={() => void meta.refetch()} />
        ) : (
          <Loading kind="table" rows={6}>
            {t('loading')}
          </Loading>
        )
      ) : active.length < 2 ? (
        <div role="note" className="panel px-5 py-6 text-sm text-ink-2">
          {t('needTwo')}
        </div>
      ) : missing ? (
        <div role="note" className="panel px-5 py-6 text-sm text-ink-2">
          {t('unavailableRoute')}
        </div>
      ) : first?.isError ? (
        <ErrorNotice error={first.error} onRetry={() => void first.refetch()} />
      ) : !data ? (
        <Loading kind="table" rows={6}>
          {t('loading')}
        </Loading>
      ) : (
        <>
          <Glance shops={shops} />
          <Prices
            shops={shops}
            pairs={pairs.map((p, i) => ({ ...p, pricing: queries[i]?.data?.data?.pricing }))}
            share={data.policySharePct}
          />
          <StockSection shops={shops} rows={data.stockouts} />
          <Ideas shops={shops} data={data} />
        </>
      )}
    </section>
  );
}

/** All shops, or one: real buttons, each shop's colour dot beside its name. */
function ShopPicker({
  shops,
  value,
  onChange,
}: {
  shops: string[];
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  const t = useTranslations('insights');
  const name = useRetailerName();
  const opts: { id: string | null; label: ReactNode }[] = [
    { id: null, label: t('all') },
    ...shops.map((s, i) => ({
      id: s,
      label: (
        <>
          <RetailerDot id={s} index={i} />
          {name(s)}
        </>
      ),
    })),
  ];
  return (
    <div role="group" aria-label={t('shops')} className="flex flex-wrap gap-1 rounded-ctl bg-surface-2 p-1">
      {opts.map((o) => (
        <button
          key={o.id ?? ''}
          type="button"
          aria-pressed={o.id === value}
          onClick={() => onChange(o.id)}
          className={`flex items-center gap-1.5 rounded-[8px] px-3 py-1 text-sm focus-visible:outline-2 ${
            o.id === value ? 'bg-surface font-semibold text-ink shadow-card' : 'text-ink-2 hover:text-ink'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A section heading, its method in an (i) tooltip beside it (outside the heading's name). */
// ---- At a glance ----------------------------------------------------------------------------

function Glance({ shops }: { shops: string[] }) {
  const t = useTranslations('insights');
  const { api } = useAuth();
  const coverage = useQuery({
    queryKey: ['coverage'],
    queryFn: ({ signal }) => api!.get('/api/v1/coverage', { signal }),
    enabled: !!api,
  });
  const fresh = (id: string) => coverage.data?.data?.retailers.find((r) => r.id === id)?.freshness ?? null;
  return (
    <section aria-labelledby="ins-glance" className="space-y-2.5">
      <Heading id="ins-glance">{t('glance.title')}</Heading>
      <div className={cols(shops.length)}>
        {shops.map((s) => (
          <GlanceTile key={s} shop={s} fresh={fresh(s)} />
        ))}
      </div>
    </section>
  );
}

/** One shop's size, the same counts as its Products list: listings, brands, listings with a price. */
function GlanceTile({ shop, fresh }: { shop: string; fresh: string | null }) {
  const t = useTranslations('insights');
  const locale = useLocale();
  const name = useRetailerName();
  const { api } = useAuth();
  const all = useQuery({
    queryKey: ['products', 'insights', shop],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/products', {
        query: { ...toQuery({ ...EMPTY, retailer: [shop] }, null), limit: 1 },
        signal,
      }),
    enabled: !!api,
  });
  const priced = useQuery({
    queryKey: ['products', 'insights', shop, 'priced'],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/products', {
        query: { ...toQuery({ ...EMPTY, retailer: [shop], priceMin: '0' }, null), limit: 1 },
        signal,
      }),
    enabled: !!api,
  });
  const page = all.data?.data;
  const n = page?.total;
  const brands = page?.facets.brand.length;
  const p = priced.data?.data?.total;
  return (
    <Panel top={shop}>
      <ShopHead id={shop} />
      <p className="mt-2 flex items-baseline gap-1.5">
        {n === undefined ? (
          <span className="text-[28px] leading-9 font-bold text-ink-3">–</span>
        ) : (
          <Link
            href={exploreHref(locale, { retailer: [shop] })}
            className="text-[28px] leading-9 font-bold text-ink underline-offset-2 hover:underline"
          >
            <Num>{formatCount(n, locale)}</Num>
          </Link>
        )}
        <span className="text-sm font-medium text-ink-2">{t('glance.products', { count: n ?? 0 })}</span>
        <Info text={t('glance.tip', { shop: name(shop) })} />
      </p>
      <p className="text-sm text-ink-2">
        {brands !== undefined &&
          t.rich('glance.brands', { num: formatCount(brands, locale), count: brands, b: boldTag })}
        {brands !== undefined && p !== undefined && ' · '}
        {p !== undefined &&
          t.rich('glance.priced', {
            num: formatCount(p, locale),
            l: linkTag(exploreHref(locale, { retailer: [shop], priceMin: '0' })),
          })}
      </p>
      {fresh && (
        <p className="mt-0.5 text-sm text-ink-2">{t('glance.asOf', { date: formatDate(fresh, locale) })}</p>
      )}
    </Panel>
  );
}

// ---- Prices across shops --------------------------------------------------------------------

type PairPricing = { base: string; other: string; pricing: Insights['pricing'] | undefined };

/**
 * Reviewed matches per pair of shops, each opening that pair's Compare view, never summed; then
 * the price cards for each pair that has some. Until a pair has reviewed matches it has no price
 * number at all.
 */
function Prices({ shops, pairs, share }: { shops: string[]; pairs: PairPricing[]; share: string }) {
  const t = useTranslations('insights');
  const locale = useLocale();
  const name = useRetailerName();
  const shown = pairs.filter((p) => shops.includes(p.base) || shops.includes(p.other));
  const ready = shown.filter((p) => p.pricing?.status === 'ok' && p.pricing.n > 0);
  return (
    <section aria-labelledby="ins-prices" className="space-y-3">
      <h2 id="ins-prices" className="sr-only">
        {t('prices.title')}
      </h2>
      <div className="rounded-card border border-dashed border-line-2 bg-surface px-4.5 py-3">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          {ready.length === 0 && <b className="font-semibold">{t('prices.waiting')}</b>}
          <span className="text-ink-2">{t('prices.sofar')}</span>
          {shown.map((p, i) => (
            <span key={`${p.base},${p.other}`} className="text-ink-2">
              {i > 0 && <span aria-hidden>· </span>}
              {p.pricing
                ? t.rich('prices.pair', {
                    a: name(p.base),
                    b: name(p.other),
                    num: formatCount(p.pricing.n, locale),
                    l: linkTag(compareHref(locale, { base: p.base, other: p.other })),
                  })
                : t.rich('prices.pair', { a: name(p.base), b: name(p.other), num: '–', l: (c) => c })}
            </span>
          ))}
          <Info text={t('prices.tip')} at="end" />
        </p>
      </div>
      {ready.map((p) => (
        <PairPrices
          key={`${p.base},${p.other}`}
          pricing={p.pricing!}
          share={share}
          base={p.base}
          other={p.other}
        />
      ))}
    </section>
  );
}

// ---- Stock today ----------------------------------------------------------------------------

function StockSection({ shops, rows }: { shops: string[]; rows: Stockouts[] }) {
  const t = useTranslations('insights');
  return (
    <section aria-labelledby="ins-stock" className="space-y-2.5">
      <Heading id="ins-stock" tip={t('stock.tip')}>
        {t('stock.title')}
      </Heading>
      <div className={cols(shops.length)}>
        {shops.map((s) => (
          <StockCard key={s} shop={s} row={rows.find((r) => r.retailer === s)} />
        ))}
      </div>
    </section>
  );
}

/**
 * One shop's stock-outs as counts. The headline is the API's outOfStock, which already leaves out
 * brands the source reports unavailable; those are a separate, plainly worded line.
 */
function StockCard({ shop, row }: { shop: string; row: Stockouts | undefined }) {
  const t = useTranslations('insights');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  if (!row || notCollected(row.reason))
    return (
      <Panel>
        <ShopHead id={shop} />
        <Off>{t('stock.off', { shop: name(shop) })}</Off>
      </Panel>
    );
  const brands = row.brands.slice(0, STOCK_BRANDS_SHOWN);
  const outHref = exploreHref(locale, {
    retailer: [shop],
    availability: ['out_of_stock'],
    unavailableBrands: 'exclude',
  });
  return (
    <Panel>
      <ShopHead id={shop} />
      {row.reason ? (
        <Off>
          <Known t={tr} v={row.reason} />
        </Off>
      ) : row.withStock === 0 ? (
        <Off>{t('stock.noStatus', { shop: name(shop) })}</Off>
      ) : (
        <>
          <p className="mt-2.5 text-[17px] font-semibold">
            {t.rich('stock.out', {
              num: formatCount(row.outOfStock, locale),
              count: row.outOfStock,
              l: linkTag(outHref),
            })}
          </p>
          <p className="text-sm text-ink-2">
            {t.rich('stock.status', {
              num: formatCount(row.withStock, locale),
              listed: formatCount(row.listed, locale),
              b: boldTag,
            })}
          </p>
          {brands.length > 0 && (
            <>
              <Label>{t('stock.brands')}</Label>
              <ul>
                {brands.map((b) => (
                  <li
                    key={b.brand}
                    className="grid grid-cols-[1fr_auto] gap-x-2.5 gap-y-1 border-t border-line py-1.5"
                  >
                    <Link
                      href={exploreHref(locale, {
                        retailer: [shop],
                        brand: [b.brand],
                        availability: ['out_of_stock'],
                      })}
                      className={`truncate text-sm ${LINK}`}
                    >
                      {b.brand}
                    </Link>
                    <span className="text-[13px] text-ink-2 tabular-nums">
                      <Num>
                        {t('stock.row', {
                          out: formatCount(b.outOfStock, locale),
                          observed: formatCount(b.observed, locale),
                        })}
                      </Num>
                    </span>
                    <span aria-hidden className="col-span-2 h-1.5 overflow-hidden rounded-full bg-line">
                      <i
                        className="block h-full"
                        style={{
                          width: `${b.observed ? (b.outOfStock / b.observed) * 100 : 0}%`,
                          background: retailerColor(shop),
                        }}
                      />
                    </span>
                  </li>
                ))}
              </ul>
              {row.brands.length > brands.length && (
                <p className="mt-1 text-xs text-ink-2">
                  {t('stock.more', {
                    count: row.brands.length - brands.length,
                    num: formatCount(row.brands.length - brands.length, locale),
                  })}
                </p>
              )}
            </>
          )}
          {row.unavailableBrands > 0 && (
            <p className="mt-3 flex flex-wrap items-center gap-1 text-[13px] text-ink-2">
              <span>
                {t.rich('stock.unavailable', {
                  num: formatCount(row.unavailableListings, locale),
                  count: row.unavailableListings,
                  brands: formatCount(row.unavailableBrands, locale),
                  brandCount: row.unavailableBrands,
                  l: linkTag(exploreHref(locale, { retailer: [shop], unavailableBrands: 'only' })),
                })}
              </span>
              <Info text={t('stock.unavailableTip')} at="end" />
            </p>
          )}
        </>
      )}
    </Panel>
  );
}
