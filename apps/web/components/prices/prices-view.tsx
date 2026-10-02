'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import { formatCount } from '@/lib/format';
import { formatMoney } from '@/lib/money';
import { ErrorNotice } from '../error-notice';
import { Card, CardGrid } from '../ui/card';
import { Known } from '../ui/known';
import { PageHeader } from '../ui/page-header';
import { Segmented } from '../ui/segmented';
import { Loading, Skeleton } from '../ui/skeleton';
import { useRetailerName } from '../use-meta';
import { PairKpis, type RetailerSummary } from '../widgets/kpis';
import { amount, compareHref, pct } from '../widgets/model';
import { useCategoryCompare } from '../widgets/use-category';
import { useCompareData, useRetailers } from '../widgets/use-compare';
import { useSummaries } from '../widgets/use-summaries';
import { CategoryCompareCard } from './category-compare';
import { brandTakeaway, gapTakeaway, histTakeaway, ladderTakeaway } from './takeaways';

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
const GapHistWidget = dynamic(() => charts().then((m) => m.GapHistWidget), {
  ssr: false,
  loading: ChartSkeleton,
});

const TOPS = [5, 10, 20] as const;
type Top = (typeof TOPS)[number];
type Pair = NonNullable<ReturnType<typeof useRetailers>['pair']>;

/**
 * Price analytics, at most four charts, each led by one line computed from its own data: one
 * retailer's full catalogue (distribution, ladder by category, brand positioning), the pair by
 * category across both full catalogues as a table (the centrepiece), then the spread of gaps on
 * the exactly matched products with the comparable-pair count beside it. The retailer and the
 * brand count live in the URL.
 */
export function PricesView() {
  const t = useTranslations('prices');
  const tw = useTranslations('widgets');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tr = useTranslations('reasons');
  const name = useRetailerName();
  const { ids, pair, loading, error } = useRetailers();
  const s = useSummaries(ids);

  const set = (k: string, v: string | null) => {
    const q = new URLSearchParams(sp.toString());
    if (v === null) q.delete(k);
    else q.set(k, v);
    const qs = q.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };
  const wanted = sp.get('retailer');
  const selected = (wanted && ids.includes(wanted) ? wanted : ids[0]) ?? null;
  // A summary the API withheld for this retailer: the page says why, never another retailer's data.
  const missing = selected ? s.missing.find((m) => m.retailer === selected) : undefined;
  // Rows are keyed by the retailer the API answered for; the asked-for id's position is the fallback.
  const row = missing
    ? undefined
    : (s.rows.find((r) => r.retailer === selected) ?? s.rows[selected ? ids.indexOf(selected) : 0]);
  const topRaw = Number(sp.get('top'));
  const top: Top = (TOPS as readonly number[]).includes(topRaw) ? (topRaw as Top) : 10;

  return (
    <div className="space-y-8">
      <PageHeader id="prices-title" title={t('title')} intro={<p>{t('intro')}</p>} />
      {error ? (
        <ErrorNotice error={error} />
      ) : loading || (s.loading && s.rows.length === 0) ? (
        <Loading kind="chart">{t('loading')}</Loading>
      ) : ids.length === 0 || (!row && !missing && !s.error) ? (
        <p className="text-sm text-ink-2">{t('noRetailers')}</p>
      ) : (
        <>
          <section aria-labelledby="per-retailer" className="space-y-4">
            <SectionHead id="per-retailer" title={t('perRetailer')} hint={t('perRetailerHint')}>
              {ids.length > 1 && (
                <Segmented
                  label={tw('controls.retailer')}
                  value={selected ?? ''}
                  options={ids.map((id) => ({ value: id, label: name(id) }))}
                  onChange={(v) => set('retailer', v === ids[0] ? null : v)}
                />
              )}
            </SectionHead>
            {s.error && !row && !missing && <ErrorNotice error={s.error.error} onRetry={s.error.retry} />}
            {missing && (
              <p role="status" className="text-sm text-ink-2">
                {t('noSummary', { retailer: name(missing.retailer) })}{' '}
                {missing.env.reason && <Known t={tr} v={missing.env.reason} />}
              </p>
            )}
            {row && (
              <RetailerSection
                row={row}
                locale={locale}
                top={top}
                onTop={(v) => set('top', v === 10 ? null : String(v))}
              />
            )}
          </section>
          {pair ? (
            <>
              <ByCategory pair={pair} locale={locale} />
              <HeadToHead pair={pair} locale={locale} />
            </>
          ) : (
            <section aria-labelledby="by-category" className="space-y-4">
              <SectionHead id="by-category" title={t('byCategory')} hint={t('onePair')} />
            </section>
          )}
        </>
      )}
    </div>
  );
}

function SectionHead({
  id,
  title,
  hint,
  children,
}: {
  id: string;
  title: string;
  hint: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h2 id={id} className="text-lg font-semibold tracking-tight">
          {title}
        </h2>
        <p className="text-sm text-ink-2">{hint}</p>
      </div>
      {children}
    </div>
  );
}

/** The line a chart leads with: its own data in one sentence, above the drawing. */
function Takeaway({ children }: { children: ReactNode }) {
  return (
    <p data-takeaway className="mb-3 text-sm font-medium text-ink">
      {children}
    </p>
  );
}

/** One retailer's catalogue; only sections /summary measured, and why the others are missing. */
function RetailerSection({
  row,
  locale,
  top,
  onTop,
}: {
  row: RetailerSummary;
  locale: string;
  top: Top;
  onTop: (v: Top) => void;
}) {
  const t = useTranslations('prices');
  const tw = useTranslations('widgets');
  const tk = useTranslations('widgets.kpi');
  const tr = useTranslations('reasons');
  const lc = locale === 'ar' ? 'ar' : 'en';
  const d = row.data;
  const p = { currency: d.currency, locale };
  const withheld = d.withheld.filter((w) => w.section === 'prices' || w.section === 'ratings');
  const topOptions = TOPS.map((n) => ({ value: n as Top, label: tw('controls.top', { n }) }));
  const hist = histTakeaway(d.priceHist);
  const ladder = ladderTakeaway(d.ladder);
  const brands = brandTakeaway(d.brandPrice, top);
  return (
    <div className="space-y-4">
      <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <Fact k={tk('products')}>{d.products === null ? tk('none') : formatCount(d.products, locale)}</Fact>
        <Fact k={tw('priced')}>{d.priced === null ? tk('none') : formatCount(d.priced, locale)}</Fact>
        <Fact k={tk('median')}>{d.medianPrice ? formatMoney(d.medianPrice, lc) : tk('none')}</Fact>
      </dl>
      {withheld.length > 0 && (
        <p className="text-sm text-ink-2">
          {t('withheld')}:{' '}
          {withheld.map((w, i) => (
            <span key={w.section}>
              {i > 0 && ' · '}
              {tw(`withheld.${w.section as 'prices' | 'ratings'}`)} <Known t={tr} v={w.reason} />
            </span>
          ))}
        </p>
      )}
      <CardGrid>
        {d.priceHist && (
          <Card
            id="p-hist"
            title={tw('hist.title')}
            question={tw('hist.question')}
            span={6}
            state={hist ? 'ready' : 'empty'}
          >
            {hist && (
              <>
                <Takeaway>
                  {tw('hist.takeaway', {
                    lo: amount(hist.lo, d.currency, locale, true),
                    hi: amount(hist.hi, d.currency, locale, true),
                    share: pct((hist.share * 100).toFixed(1), locale),
                  })}
                </Takeaway>
                <PriceHistWidget data={d.priceHist} {...p} />
              </>
            )}
          </Card>
        )}
        {d.ladder && (
          <Card
            id="p-ladder"
            title={tw('ladder.title')}
            question={tw('ladder.question')}
            span={6}
            state={ladder ? 'ready' : 'empty'}
          >
            {ladder && (
              <>
                <Takeaway>
                  {ladder.n === 1
                    ? tw('ladder.takeawayOne', {
                        cat: ladder.low.category,
                        median: formatMoney(ladder.low.median, lc),
                      })
                    : tw('ladder.takeaway', {
                        lowCat: ladder.low.category,
                        low: formatMoney(ladder.low.median, lc),
                        highCat: ladder.high.category,
                        high: formatMoney(ladder.high.median, lc),
                      })}
                </Takeaway>
                <LadderWidget data={d.ladder} {...p} />
              </>
            )}
          </Card>
        )}
        {d.brandPrice && (
          <Card
            id="p-brands"
            title={tw('brands.title')}
            question={tw('brands.question', { n: Math.min(top, d.brandPrice.length) })}
            span={12}
            state={brands ? 'ready' : 'empty'}
            tools={
              // A choice only once there are more brands than the smallest cut.
              d.brandPrice.length > TOPS[0] && (
                <Segmented
                  label={tw('controls.topLabel')}
                  value={top}
                  options={topOptions.filter((o) => o.value <= d.brandPrice!.length || o.value === top)}
                  onChange={onTop}
                />
              )
            }
          >
            {brands && (
              <>
                <Takeaway>
                  {brands.n === 1
                    ? tw('brands.takeawayOne', {
                        brand: brands.low.brand,
                        median: formatMoney(brands.low.median, lc),
                      })
                    : tw('brands.takeaway', {
                        n: brands.n,
                        high: brands.high.brand,
                        highPrice: formatMoney(brands.high.median, lc),
                        low: brands.low.brand,
                        lowPrice: formatMoney(brands.low.median, lc),
                      })}
                </Takeaway>
                <BrandPriceWidget data={d.brandPrice} top={top} {...p} />
              </>
            )}
          </Card>
        )}
      </CardGrid>
    </div>
  );
}

function Fact({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-ink-2">{k}</dt>
      <dd className="font-semibold tabular-nums">{children}</dd>
    </div>
  );
}

/** The centrepiece: the pair by shared category over both full catalogues, as a table. */
function ByCategory({ pair, locale }: { pair: Pair; locale: string }) {
  const t = useTranslations('prices');
  const state = useCategoryCompare(pair);
  const names = { base: pair.name(pair.base), other: pair.name(pair.other) };
  return (
    <section aria-labelledby="by-category" className="space-y-4">
      <SectionHead id="by-category" title={t('byCategory')} hint={t('byCategoryHint', names)} />
      <CardGrid>
        <CategoryCompareCard state={state} pair={pair} locale={locale} />
      </CardGrid>
    </section>
  );
}

/** The pair on the exactly matched set only: the headline numbers and the spread of gaps, on n. */
function HeadToHead({ pair, locale }: { pair: Pair; locale: string }) {
  const t = useTranslations('prices');
  const tw = useTranslations('widgets');
  const tc = useTranslations('card');
  const tr = useTranslations('reasons');
  const cmp = useCompareData(pair);
  const names = { base: pair.name(pair.base), other: pair.name(pair.other) };
  const href = compareHref(locale, pair);
  // The n every head-to-head figure is on; without a summary there is nothing to put a count to.
  const n = cmp.kind === 'ready' ? cmp.data.summary?.n : undefined;
  const nPairs = n === undefined ? null : tw('nPairs', { n });
  const head = (
    <SectionHead
      id="head-to-head"
      title={t('headToHead')}
      hint={
        <>
          {t('headToHeadHint', names)}
          {nPairs && (
            <>
              {' '}
              <span className="font-medium tabular-nums">{nPairs}</span>
            </>
          )}
        </>
      }
    >
      <Link href={href} className="btn text-sm focus-visible:outline-2">
        {t('openCompare')}
      </Link>
    </SectionHead>
  );
  if (cmp.kind === 'loading')
    return (
      <section aria-labelledby="head-to-head" className="space-y-4">
        {head}
        <Loading kind="chart">{tc('loading')}</Loading>
      </section>
    );
  if (cmp.kind === 'error')
    return (
      <section aria-labelledby="head-to-head" className="space-y-4">
        {head}
        <ErrorNotice error={cmp.error} onRetry={cmp.retry} />
      </section>
    );
  if (cmp.kind === 'empty')
    return (
      <section aria-labelledby="head-to-head" className="space-y-4">
        {head}
        <p className="text-sm text-ink-2">
          {t('noPairs')} {cmp.env?.reason && <Known t={tr} v={cmp.env.reason} />}
        </p>
      </section>
    );
  const data = cmp.data;
  const gap = gapTakeaway(data.summary?.gapHist);
  const currency = data.summary?.basket.base.currency ?? '';
  const share = (v: number) => pct((v * 100).toFixed(1), locale);
  return (
    <section aria-labelledby="head-to-head" className="space-y-4">
      {head}
      <PairKpis data={data} pair={pair} locale={locale} href={href} />
      {data.summary && (
        <CardGrid>
          <Card
            id="p-gap-hist"
            title={tw('gapHist.title')}
            meta={nPairs}
            question={tw('gapHist.question', { other: names.other })}
            span={12}
            state={gap ? 'ready' : 'empty'}
            reason={cmp.env.reason ? <Known t={tr} v={cmp.env.reason} /> : undefined}
          >
            {gap && (
              <>
                <Takeaway>
                  {tw(gap.same > 0 ? 'gapHist.takeawaySame' : 'gapHist.takeaway', {
                    other: names.other,
                    n: gap.n,
                    dearer: share(gap.dearer),
                    cheaper: share(gap.cheaper),
                    same: share(gap.same),
                  })}
                </Takeaway>
                <GapHistWidget data={data.summary.gapHist} currency={currency} locale={locale} pair={pair} />
              </>
            )}
          </Card>
        </CardGrid>
      )}
    </section>
  );
}
