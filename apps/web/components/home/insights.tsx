'use client';

import dynamic from 'next/dynamic';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Bucket, CategoryCompare } from '@/lib/api/category-compare';
import { formatDate } from '@/lib/format';
import { formatMoney } from '@/lib/money';
import { Card, CardGrid } from '../ui/card';
import { Pct } from '../ui/money';
import { Skeleton } from '../ui/skeleton';
import { brandTakeaway, histTakeaway, ladderTakeaway } from '../prices/takeaways';
import { BRANDS_TOP, SHARE_TOP } from '../widgets/constants';
import type { RetailerSummary } from '../widgets/kpis';
import { amount, brandShare, pct, promotions, trendPoints } from '../widgets/model';
import { useIndexData, type PairState } from '../widgets/use-compare';
import { deepestBand, depthBands, peakDay, widestGap } from './model';
import type { useLaunchCounts } from './use-overview-data';

const charts = () => import('../widgets/charts');
const ChartSkeleton = () => <Skeleton kind="chart" />;
const PriceHistWidget = dynamic(() => charts().then((m) => m.PriceHistWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const LadderWidget = dynamic(() => charts().then((m) => m.LadderWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const BrandPriceWidget = dynamic(() => charts().then((m) => m.BrandPriceWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const BrandShareWidget = dynamic(() => charts().then((m) => m.BrandShareWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const PromoDepthWidget = dynamic(() => charts().then((m) => m.PromoDepthWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const IndexTrendWidget = dynamic(() => charts().then((m) => m.IndexTrendWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const BucketGapWidget = dynamic(() => charts().then((m) => m.BucketGapWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const LaunchChart = dynamic(() => import('./launch-chart').then((m) => m.LaunchChart), {
  ssr: false,
  loading: ChartSkeleton,
});

type Pair = { base: string; other: string; name: (id: string) => string };

/**
 * The charts that dig into the data, each under one line stating what it shows, computed from
 * the same slice of the API it draws (components/prices/takeaways.ts): the pair's price gaps by
 * category and index over time, launches per day, then each shop's price bands, category
 * ladder, brand positioning, brand concentration and discount depth. A section /summary withheld
 * draws nothing here; the band's chip already says so.
 */
export function Insights({
  rows,
  pair,
  cat,
  launches,
}: {
  rows: readonly RetailerSummary[];
  pair: Pair | null;
  cat: PairState<CategoryCompare>;
  launches: ReturnType<typeof useLaunchCounts>;
}) {
  const t = useTranslations('home.insights');
  const tw = useTranslations('widgets');
  const locale = useLocale();
  const lc = locale === 'ar' ? 'ar' : 'en';
  const index = useIndexData(pair);
  const series = launches.shops
    .filter((l) => l.state === 'ready' && l.perDay && l.perDay.length > 0)
    .map((l) => ({
      id: l.shop.id,
      name: l.shop.name,
      index: rows.findIndex((r) => r.retailer === l.shop.id),
      perDay: l.perDay!,
    }));
  const launched = series.flatMap((s) => s.perDay);
  const peak = peakDay(
    launched.reduce<{ date: string; n: number }[]>((acc, d) => {
      const hit = acc.find((x) => x.date === d.date);
      if (hit) hit.n += d.n;
      else acc.push({ ...d });
      return acc;
    }, []),
  );
  const launchTotal = series.reduce((s, x) => s + x.perDay.reduce((a, d) => a + d.n, 0), 0);
  const trend = index.kind === 'ready' ? trendPoints(index.data) : null;
  const buckets =
    cat.kind === 'ready' ? cat.data.buckets.filter((b) => b.status === 'ok' && b.gapPct !== null) : [];
  const widest = widestBucket(buckets);
  const label = (b: Bucket) => b.label?.[lc] || tw(`categories.name.${b.key}`);

  return (
    <section aria-labelledby="insights-title" className="space-y-5">
      <h2 id="insights-title" className="sr-only">
        {t('title')}
      </h2>
      <CardGrid>
        {pair && (cat.kind === 'loading' || widest) && (
          <Card
            id="i-gaps"
            span={trend ? 6 : 12}
            state={cat.kind === 'loading' ? 'loading' : 'ready'}
            skeleton="chart"
            title={
              widest
                ? t.rich('gaps', {
                    category: label(widest),
                    other: pair.name(pair.other),
                    base: pair.name(pair.base),
                    pct: () => <Pct v={widest.gapPct!} />,
                  })
                : tw('buckets.title')
            }
            meta={<Kind>{tw('buckets.title')}</Kind>}
          >
            {widest && (
              <BucketGapWidget
                data={buckets}
                currency={widest.sides[pair.base]?.median?.currency ?? ''}
                locale={locale}
                pair={pair}
                label={label}
              />
            )}
          </Card>
        )}
        {pair && trend && index.kind === 'ready' && (
          <Card
            id="i-index"
            span={widest ? 6 : 12}
            title={t('index', {
              other: pair.name(pair.other),
              base: pair.name(pair.base),
              latest: trend[trend.length - 1]!.index,
              first: trend[0]!.index,
              date: formatDate(trend[0]!.date, locale),
            })}
            meta={<Kind>{tw('index.title')}</Kind>}
          >
            <IndexTrendWidget data={index.data} currency="" locale={locale} pair={pair} />
          </Card>
        )}
        {series.length > 0 && (
          <Card
            id="i-launches"
            span={12}
            title={
              peak
                ? t('launches', {
                    n: launchTotal,
                    days: series[0]!.perDay.length,
                    date: formatDate(peak.date, locale),
                    peak: peak.n,
                  })
                : t('noLaunches', { days: series[0]!.perDay.length })
            }
            meta={<Kind>{t('launchesKind')}</Kind>}
          >
            <LaunchChart series={series} locale={locale} />
          </Card>
        )}
        {rows.map((r, i) => (
          <ShopCharts key={r.retailer} row={r} index={i} />
        ))}
      </CardGrid>
    </section>
  );
}

/** The chart's kind, in small type under the finding: what the chart is, not what it says. */
const Kind = ({ children }: { children: ReactNode }) => (
  <span className="font-normal text-ink-3">{children}</span>
);

/** The bucket with the widest gap the API computed; null when none was. */
function widestBucket(buckets: readonly Bucket[]): Bucket | null {
  const max = widestGap(buckets);
  return buckets.find((b) => Math.abs(Number(b.gapPct)) === max) ?? null;
}

/** One shop's charts, each only when /summary measured its section and the line can be said. */
function ShopCharts({ row, index }: { row: RetailerSummary; index: number }) {
  const t = useTranslations('home.insights');
  const tw = useTranslations('widgets');
  const locale = useLocale();
  const lc = locale === 'ar' ? 'ar' : 'en';
  const d = row.data;
  const p = { currency: d.currency, locale };
  const id = (k: string) => `i-${k}-${index}`;
  const hist = histTakeaway(d.priceHist);
  const ladder = ladderTakeaway(d.ladder);
  const brands = brandTakeaway(d.brandPrice, BRANDS_TOP);
  const shares = brandShare(d.brandPrice, d.priced).slice(0, SHARE_TOP);
  const topShare = shares[shares.length - 1];
  const promo = promotions(d);
  const band = promo.measured ? deepestBand(promo.depth) : null;
  const shop = row.name;
  return (
    <>
      {d.priceHist && hist && (
        <Card
          id={id('hist')}
          span={6}
          title={t('hist', {
            shop,
            share: pct((hist.share * 100).toFixed(1), locale),
            lo: amount(hist.lo, d.currency, locale, true),
            hi: amount(hist.hi, d.currency, locale, true),
          })}
          meta={<Kind>{tw('hist.title')}</Kind>}
        >
          <PriceHistWidget data={d.priceHist} {...p} />
        </Card>
      )}
      {d.ladder && ladder && (
        <Card
          id={id('ladder')}
          span={6}
          title={
            ladder.n === 1
              ? t('ladderOne', { shop, cat: ladder.low.category, median: formatMoney(ladder.low.median, lc) })
              : t('ladder', {
                  shop,
                  lowCat: ladder.low.category,
                  low: formatMoney(ladder.low.median, lc),
                  highCat: ladder.high.category,
                  high: formatMoney(ladder.high.median, lc),
                })
          }
          meta={<Kind>{tw('ladder.title')}</Kind>}
        >
          <LadderWidget data={d.ladder} {...p} />
        </Card>
      )}
      {d.brandPrice && brands && (
        <Card
          id={id('brands')}
          span={6}
          title={
            brands.n === 1
              ? t('brandsOne', { shop, brand: brands.low.brand, median: formatMoney(brands.low.median, lc) })
              : t('brands', {
                  shop,
                  high: brands.high.brand,
                  highPrice: formatMoney(brands.high.median, lc),
                  low: brands.low.brand,
                  lowPrice: formatMoney(brands.low.median, lc),
                })
          }
          meta={<Kind>{tw('brands.title')}</Kind>}
        >
          <BrandPriceWidget data={d.brandPrice} top={BRANDS_TOP} {...p} />
        </Card>
      )}
      {d.brandPrice && d.priced !== null && topShare && (
        <Card
          id={id('share')}
          span={6}
          title={t('share', { shop, k: shares.length, share: pct(topShare.cum.toFixed(1), locale) })}
          meta={<Kind>{tw('share.title')}</Kind>}
        >
          <BrandShareWidget data={d.brandPrice} priced={d.priced} quiet {...p} />
        </Card>
      )}
      {promo.measured && band && (
        <Card
          id={id('depth')}
          span={12}
          title={t('depth', {
            shop,
            n: depthBands(promo.depth).total,
            band: tw('promo.off', { band: band.band }),
          })}
          meta={<Kind>{tw('promo.title')}</Kind>}
        >
          <PromoDepthWidget data={promo.depth} {...p} />
        </Card>
      )}
    </>
  );
}
