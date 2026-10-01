'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import { formatCount, formatDate } from '@/lib/format';
import type { Schemas } from '@/lib/api/types';
import { DatasetStatus } from '../dataset-status';
import { ErrorNotice } from '../error-notice';
import { Card, CardGrid } from '../ui/card';
import { CaveatNotes, EnvNotes } from '../ui/env-notes';
import { Known } from '../ui/known';
import { PageHeader } from '../ui/page-header';
import { Loading, Skeleton } from '../ui/skeleton';
import { KpiWidget, PairKpis, type RetailerSummary } from '../widgets/kpis';
import { TopDiscountsWidget } from '../widgets/top-discounts';
import { useCompareData, useIndexData, useRetailers } from '../widgets/use-compare';
import { useSummaries } from '../widgets/use-summaries';
import { BRANDS_TOP, CROSS_COLS, CROSS_ROWS, MIN_PAIRS } from '../widgets/constants';
import {
  brandShare,
  categoryNodes,
  cheaperShares,
  compareHref,
  crossCells,
  freshness,
  gapRows,
  importedOn,
  ladderRows,
  pct,
  promotions,
  promotionsHref,
  WITHHELD_REASONS,
} from '../widgets/model';

// The charts (and ECharts with them) load after the page: the KPIs and the table come first.
const charts = () => import('../widgets/charts');
// Holds the chart's place while its code loads, so the cards do not jump.
const ChartSkeleton = () => <Skeleton kind="chart" />;
const LadderWidget = dynamic(() => charts().then((m) => m.LadderWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const BrandPriceWidget = dynamic(() => charts().then((m) => m.BrandPriceWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const CategoryMixWidget = dynamic(() => charts().then((m) => m.CategoryMixWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const PriceHistWidget = dynamic(() => charts().then((m) => m.PriceHistWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const BrandShareWidget = dynamic(() => charts().then((m) => m.BrandShareWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const RatingPriceWidget = dynamic(() => charts().then((m) => m.RatingPriceWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const CrossHeatmapWidget = dynamic(() => charts().then((m) => m.CrossHeatmapWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const CheaperShareWidget = dynamic(() => charts().then((m) => m.CheaperShareWidget), {
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
const TopGapsWidget = dynamic(() => charts().then((m) => m.TopGapsWidget), {
  ssr: false,
  loading: ChartSkeleton,
});

type View = 'overview' | 'compare';
type Pair = NonNullable<ReturnType<typeof useRetailers>['pair']>;

/**
 * The landing: each retailer's catalogue at a glance, the two head to head on the matched set,
 * and the discounts of the retailers whose was-prices are verified.
 */
export function Landing() {
  const t = useTranslations('home.landing');
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const view: View = sp.get('view') === 'compare' ? 'compare' : 'overview';
  const go = (v: View) =>
    router.replace(v === 'compare' ? `${pathname}?view=compare` : pathname, { scroll: false });
  const { ids, pair, loading, error } = useRetailers();
  const s = useSummaries(ids);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t('overview')}
        intro={<Subtitle rows={s.rows} />}
        tools={
          <div role="tablist" aria-label={t('tabs')} className="flex gap-1 rounded-ctl bg-surface-2 p-1">
            {(['overview', 'compare'] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                id={`tab-${v}`}
                aria-selected={view === v}
                aria-controls={`panel-${v}`}
                tabIndex={view === v ? 0 : -1}
                onClick={() => go(v)}
                onKeyDown={(e) => {
                  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                    const next = view === 'overview' ? 'compare' : 'overview';
                    go(next);
                    document.getElementById(`tab-${next}`)?.focus();
                  }
                }}
                className={`rounded-[8px] px-4 py-1.5 text-sm focus-visible:outline-2 ${
                  view === v ? 'bg-surface font-semibold text-ink shadow-card' : 'text-ink-2 hover:text-ink'
                }`}
              >
                {t(v === 'overview' ? 'overview' : 'compareTab')}
              </button>
            ))}
          </div>
        }
      />
      <div role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`}>
        {error ? (
          <ErrorNotice error={error} />
        ) : loading ? (
          <Loading kind="chart">{t('loading')}</Loading>
        ) : view === 'overview' ? (
          <Overview s={s} pair={pair} />
        ) : (
          <ComparePreview s={s} pair={pair} />
        )}
      </div>
    </div>
  );
}

/** One line per retailer: its snapshot date, or its import date when it was imported. */
function Subtitle({ rows }: { rows: readonly RetailerSummary[] }) {
  const t = useTranslations('home.landing');
  const locale = useLocale();
  if (rows.length === 0) return <p>{t('intro')}</p>;
  return (
    <>
      {rows.map((r) => {
        // An imported retailer's date is when it was imported; it is never called a snapshot date.
        const imported =
          freshness(r.data.freshness) === 'snapshot' || importedOn(r.caveats, r.retailer)
            ? (importedOn(r.caveats, r.retailer) ?? r.data.freshness.cutoff)
            : null;
        return (
          <p key={r.retailer}>
            {t(imported ? 'subtitleImported' : 'subtitle', {
              retailer: r.name,
              date: formatDate(imported ?? r.data.asOf, locale),
            })}
          </p>
        );
      })}
    </>
  );
}

/** The per-retailer widgets, one card per retailer per chart; `id`s stay unsuffixed for the first. */
function RetailerCharts({ rows, locale }: { rows: readonly RetailerSummary[]; locale: string }) {
  const tw = useTranslations('widgets');
  const many = rows.length > 1;
  const cards: ((span: 6 | 12) => React.JSX.Element)[] = [];
  const card = (key: string, r: RetailerSummary, i: number, question: string) => ({
    id: `w-${key}${i === 0 ? '' : `-${r.retailer}`}`,
    title: many ? tw('retailerLabel', { title: tw(`${key}.title`), retailer: r.name }) : tw(`${key}.title`),
    question,
  });
  const add = (f: (r: RetailerSummary, i: number) => ((span: 6 | 12) => React.JSX.Element) | false | null) =>
    rows.forEach((r, i) => {
      const c = f(r, i);
      if (c) cards.push(c);
    });
  // Only widgets the snapshot can fill: never an empty card. Null sections are withheld.
  add((r, i) => {
    const { brandPrice } = r.data;
    const p = { currency: r.data.currency, locale };
    return (
      !!brandPrice &&
      brandPrice.length > 0 &&
      ((span) => (
        <Card
          key={`brands-${r.retailer}`}
          span={span}
          {...card('brands', r, i, tw('brands.question', { n: Math.min(BRANDS_TOP, brandPrice.length) }))}
        >
          <BrandPriceWidget data={brandPrice} {...p} />
        </Card>
      ))
    );
  });
  add((r, i) => {
    const { ladder } = r.data;
    const p = { currency: r.data.currency, locale };
    return (
      !!ladder &&
      ladderRows(ladder).length > 0 &&
      ((span) => (
        <Card key={`ladder-${r.retailer}`} span={span} {...card('ladder', r, i, tw('ladder.question'))}>
          <LadderWidget data={ladder} {...p} />
        </Card>
      ))
    );
  });
  add((r, i) => {
    const { priceHist } = r.data;
    const p = { currency: r.data.currency, locale };
    return (
      !!priceHist &&
      priceHist.counts.some((c) => c > 0) &&
      ((span) => (
        <Card key={`hist-${r.retailer}`} span={span} {...card('hist', r, i, tw('hist.question'))}>
          <PriceHistWidget data={priceHist} {...p} />
        </Card>
      ))
    );
  });
  add((r, i) => {
    const { categoryMix } = r.data;
    const p = { currency: r.data.currency, locale };
    return (
      !!categoryMix &&
      categoryNodes(categoryMix).length > 0 &&
      ((span) => (
        <Card key={`mix-${r.retailer}`} span={span} {...card('mix', r, i, tw('mix.question'))}>
          <CategoryMixWidget data={categoryMix} {...p} />
        </Card>
      ))
    );
  });
  add((r, i) => {
    const { ratingPrice } = r.data;
    const p = { currency: r.data.currency, locale };
    return (
      !!ratingPrice &&
      ratingPrice.points.length > 0 &&
      ((span) => (
        <Card key={`rating-${r.retailer}`} span={span} {...card('rating', r, i, tw('rating.question'))}>
          <RatingPriceWidget data={ratingPrice} {...p} />
          <RatingNote data={ratingPrice} />
        </Card>
      ))
    );
  });
  add((r, i) => {
    const { brandPrice, priced } = r.data;
    const p = { currency: r.data.currency, locale };
    return (
      !!brandPrice &&
      !!priced &&
      brandShare(brandPrice, priced).length > 0 &&
      ((span) => (
        <Card key={`share-${r.retailer}`} span={span} {...card('share', r, i, tw('share.question'))}>
          <BrandShareWidget data={brandPrice} priced={priced} {...p} />
        </Card>
      ))
    );
  });
  if (cards.length === 0) return null;
  return (
    <CardGrid>
      {/* Two per row; an odd one out takes the full row. */}
      {cards.map((c, i) => c(i === cards.length - 1 && cards.length % 2 === 1 ? 12 : 6))}
    </CardGrid>
  );
}

function RatingNote({ data }: { data: { n: number; ratedPct: string; points: unknown[] } }) {
  const t = useTranslations('widgets.rating');
  const locale = useLocale();
  return (
    <p className="mt-1 text-xs text-ink-2">
      {t('note', {
        rated: pct(data.ratedPct, locale),
        n: formatCount(data.n, locale),
        k: data.points.length,
      })}
    </p>
  );
}

/**
 * Why price or rating cards are missing for a retailer: /summary's own reason per withheld
 * section. Promotions are left out; they wait on the Compare tab with their reason as the caption.
 */
function WithheldNote({ rows }: { rows: readonly RetailerSummary[] }) {
  const t = useTranslations('widgets.withheld');
  const tr = useTranslations('reasons');
  const many = rows.length > 1;
  const lines = rows.flatMap((r) =>
    r.data.withheld
      .filter((w) => w.section === 'prices' || w.section === 'ratings')
      .map((w) => ({
        key: `${r.retailer}:${w.section}`,
        name: r.name,
        section: w.section as 'prices' | 'ratings',
        reason: w.reason,
      })),
  );
  if (lines.length === 0) return null;
  return (
    <div role="note" className="space-y-1 panel px-4 py-3 text-sm">
      {lines.map((w) => (
        <p key={w.key}>
          {many && <b className="font-semibold">{w.name}: </b>}
          {t(w.section)} <Known t={tr} v={w.reason} />
        </p>
      ))}
    </div>
  );
}

function Overview({ s, pair }: { s: ReturnType<typeof useSummaries>; pair: Pair | null }) {
  const t = useTranslations('home.landing');
  const tw = useTranslations('widgets');
  const tt = useTranslations('widgets.top');
  const tc = useTranslations('card');
  const locale = useLocale();

  if (s.error && s.rows.length === 0) return <ErrorNotice error={s.error.error} onRetry={s.error.retry} />;
  if (s.loading && s.rows.length === 0) return <Loading kind="chart">{tc('loading')}</Loading>;
  if (s.rows.length === 0)
    return (
      <div className="space-y-6">
        {s.empty.length > 0 ? (
          <EnvNotes env={s.empty[0]!} />
        ) : (
          <p className="text-sm text-ink-2">{t('noRetailers')}</p>
        )}
        <Dataset />
      </div>
    );

  const many = s.rows.length > 1;
  // Discounts only where the retailer's was-prices are verified: /summary measures them or says why not.
  const promoRows = s.rows.filter((r) => promotions(r.data).measured);
  return (
    <div className="space-y-6">
      {s.rows.map((r) => (
        <CaveatNotes key={r.retailer} caveats={r.caveats} />
      ))}
      {s.empty.map((e, i) => (
        <EnvNotes key={`empty-${i}`} env={e} />
      ))}
      <WithheldNote rows={s.rows} />
      <KpiWidget rows={s.rows} locale={locale} />
      <p className="text-xs text-ink-2">{tw('drill')}</p>
      <RetailerCharts rows={s.rows} locale={locale} />
      {pair && <HeadToHead pair={pair} />}
      {promoRows.length > 0 && (
        <CardGrid>
          {promoRows.map((r, i) => {
            const promo = promotions(r.data);
            if (!promo.measured) return null;
            const suffix = i === 0 ? '' : `-${r.retailer}`;
            const only = many ? (
              <span className="pill bg-blush text-blush-ink">{tw('kpi.only', { retailer: r.name })}</span>
            ) : null;
            const p = { currency: r.data.currency, locale };
            return [
              promo.depth.category.length > 0 && (
                <Card
                  key={`promo${suffix}`}
                  id={`w-promo${suffix}`}
                  title={tw('promo.title')}
                  question={tw('promo.question')}
                  span={6}
                  tools={only}
                >
                  <PromoDepthWidget data={promo.depth} {...p} />
                </Card>
              ),
              promo.top.length > 0 && (
                <Card
                  key={`top${suffix}`}
                  id={`w-top${suffix}`}
                  title={tt('title')}
                  question={tt('question')}
                  span={promo.depth.category.length > 0 ? 6 : 12}
                  flush
                  tools={
                    <>
                      {only}
                      <Link href={promotionsHref(locale, {})} className="btn text-sm focus-visible:outline-2">
                        {tt('all')}
                      </Link>
                    </>
                  }
                >
                  <TopDiscountsWidget data={promo.top} locale={locale} retailer={r.retailer} />
                </Card>
              ),
            ];
          })}
        </CardGrid>
      )}
      <Dataset />
    </div>
  );
}

/**
 * The pair on the matched set only: the comparable-pair count sits in every card's question, so
 * no head-to-head number reads as a full-catalogue comparison.
 */
function HeadToHead({ pair }: { pair: Pair }) {
  const t = useTranslations('home.landing');
  const tw = useTranslations('widgets');
  const tc = useTranslations('card');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  // Every pair in one response where it fits (the heatmap needs them all); the server's groups
  // only when it does not.
  const cmp = useCompareData(pair, null, 500);
  const truncated = cmp.kind === 'ready' && cmp.data.truncated;
  const byCat = useCompareData(truncated ? pair : null, 'category');
  const byBrand = useCompareData(truncated ? pair : null, 'brand');
  const idx = useIndexData(pair);
  const href = compareHref(locale, pair);
  const heading = (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{t('headToHead')}</h2>
        <p className="text-sm text-ink-2">{tw('matchedOnly')}</p>
      </div>
      <Link href={`/${locale}/prices/`} className="btn text-sm focus-visible:outline-2">
        {t('openPrices')}
      </Link>
    </div>
  );
  if (cmp.kind === 'loading')
    return (
      <section className="space-y-4">
        {heading}
        <Loading kind="lines">{tc('loading')}</Loading>
      </section>
    );
  if (cmp.kind === 'error')
    return (
      <section className="space-y-4">
        {heading}
        <ErrorNotice error={cmp.error} onRetry={cmp.retry} />
      </section>
    );
  if (cmp.kind === 'empty')
    return (
      <section className="space-y-4">
        {heading}
        <p className="text-sm text-ink-2">
          {t('noPairs')} {cmp.env?.reason && <Known t={tr} v={cmp.env.reason} />}
        </p>
      </section>
    );
  const data = cmp.data;
  const n = data.summary?.n;
  // The n every head-to-head card is on; without a summary there is nothing to put a count to.
  const nPairs = n === undefined ? null : tw('nPairs', { n });
  const gaps = gapRows(data.rows, 10);
  const cross = truncated
    ? null
    : crossCells(data.rows, { min: MIN_PAIRS, maxRows: CROSS_ROWS, maxCols: CROSS_COLS });
  const currency = data.summary?.basket.base.currency ?? gaps[0]?.basePrice?.currency ?? '';
  const names = { base: pair.name(pair.base), other: pair.name(pair.other) };
  const shareCard = (state: typeof byCat, groupBy: 'category' | 'brand') => (
    <Card
      id={`w-share-${groupBy}`}
      title={tw('cheaperShare.title', {
        by: tw(groupBy === 'brand' ? 'cheaperShare.byBrand' : 'cheaperShare.byCategory'),
      })}
      meta={nPairs}
      question={tw('cheaperShare.question', {
        by: tw(groupBy === 'brand' ? 'cheaperShare.byBrand' : 'cheaperShare.byCategory'),
      })}
      span={6}
      state={state.kind === 'loading' ? 'loading' : state.kind === 'error' ? 'error' : 'ready'}
      skeleton="chart"
      reason={state.kind === 'error' ? <ErrorNotice error={state.error} onRetry={state.retry} /> : undefined}
    >
      {state.kind === 'ready' && cheaperShares(state.data.groups, pair.base, pair.other).length > 0 ? (
        <CheaperShareWidget
          data={state.data.groups}
          currency={currency}
          locale={locale}
          pair={pair}
          groupBy={groupBy}
        />
      ) : state.kind === 'ready' ? (
        <p className="text-sm text-ink-2">
          {tw('cheaperShare.thin', {
            n: state.data.groups.length,
            list: state.data.groups.map((g) => g.key).join(', '),
          })}
        </p>
      ) : null}
    </Card>
  );
  return (
    <section className="space-y-4" aria-label={t('headToHead')}>
      {heading}
      <PairKpis data={data} pair={pair} locale={locale} href={href} />
      <CardGrid>
        {cross && cross.cells.length > 0 && (
          <Card
            id="w-cross"
            title={tw('cross.title')}
            meta={nPairs}
            question={tw('cross.question')}
            span={12}
          >
            <CrossHeatmapWidget data={data.rows} currency={currency} locale={locale} pair={pair} />
          </Card>
        )}
        {truncated && (
          <>
            <p className="col-span-12 text-sm text-ink-2">{tw('cross.truncated')}</p>
            {shareCard(byCat, 'category')}
            {shareCard(byBrand, 'brand')}
          </>
        )}
        {gaps.length > 0 && (
          <Card id="w-gaps" title={tw('gaps.title')} meta={nPairs} question={tw('gaps.question')} span={8}>
            <TopGapsWidget data={data.rows} currency={currency} locale={locale} pair={pair} />
          </Card>
        )}
        <Card
          id="w-index"
          title={tw('index.title')}
          meta={nPairs}
          question={tw('index.question', names)}
          span={gaps.length > 0 ? 4 : 12}
          state={idx.kind === 'loading' ? 'loading' : 'ready'}
          skeleton="chart"
        >
          {idx.kind === 'ready' ? (
            <IndexTrendWidget data={idx.data} currency={currency} locale={locale} pair={pair} />
          ) : idx.kind === 'error' ? (
            <ErrorNotice error={idx.error} onRetry={idx.retry} />
          ) : (
            // No points at all: the same line as an index without history (owner rule).
            <p className="text-sm text-ink-2">{tw('index.noHistory')}</p>
          )}
        </Card>
      </CardGrid>
    </section>
  );
}

function Dataset() {
  return (
    <section id="dataset" className="panel scroll-mt-6 px-5 py-4">
      <DatasetStatus nested />
    </section>
  );
}

/**
 * The Compare tab: the assortment overlap from /compare when the pair exists, the layout the index
 * and gap cards use when it does not, and a preview for each promotion widget a retailer withholds,
 * with the API's own reason as the caption.
 */
function ComparePreview({ s, pair }: { s: ReturnType<typeof useSummaries>; pair: Pair | null }) {
  const t = useTranslations('home.landing');
  const locale = useLocale();
  const tw = useTranslations('widgets');
  const cmp = useCompareData(pair);
  const many = s.rows.length > 1;
  const previews: [string, string, ReactNode][] = [];
  if (cmp.kind !== 'ready') {
    previews.push(
      [t('indexTitle'), t('indexQuestion'), t('indexReason')],
      [t('gapTitle'), t('gapQuestion'), t('gapReason')],
      [t('overlapTitle'), t('overlapQuestion'), t('overlapReason')],
    );
  }
  // Promotion widgets a retailer withholds: one preview per widget, with each retailer's reason.
  const withheld = s.rows.flatMap((r) => {
    const p = promotions(r.data);
    return p.measured ? [] : [{ name: r.name, reason: p.reason }];
  });
  if (withheld.length > 0) {
    const why = (
      <>
        {withheld.map((w) => {
          const text = (WITHHELD_REASONS as readonly string[]).includes(w.reason)
            ? t(`withheld.${w.reason as (typeof WITHHELD_REASONS)[number]}`)
            : t('withheld.other');
          return (
            <span key={w.name} className="block">
              {many ? `${w.name}: ${text}` : text}
            </span>
          );
        })}
      </>
    );
    previews.push([tw('promo.title'), tw('promo.question'), why], [tw('top.title'), tw('top.question'), why]);
  }
  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm text-ink-2">{t('compareNote')}</p>
      <CardGrid>
        {pair && cmp.kind === 'ready' && (
          <Card
            id="w-overlap"
            title={t('overlapTitle')}
            question={t('overlapQuestion')}
            span={12}
            tools={
              <Link href={compareHref(locale, pair)} className="btn text-sm focus-visible:outline-2">
                {t('openCompare')}
              </Link>
            }
          >
            <Overlap sides={cmp.data.sides} pair={pair} />
          </Card>
        )}
        {previews.map(([title, q, reason], i) => (
          <Card
            key={i}
            id={`preview-${i}`}
            title={title}
            question={q}
            span={i === 0 && cmp.kind !== 'ready' ? 12 : 6}
            state="preview"
            reason={reason}
            tools={
              i === 0 && cmp.kind !== 'ready' ? (
                <Link href={`/${locale}/compare/`} className="btn text-sm focus-visible:outline-2">
                  {t('openCompare')}
                </Link>
              ) : undefined
            }
          />
        ))}
      </CardGrid>
    </div>
  );
}

/** Each side's observed, counted and only-here products, as /compare sent them. */
function Overlap({ sides, pair }: { sides: Schemas['Sides']; pair: Pair }) {
  const t = useTranslations('home.landing.overlap');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {(['base', 'other'] as const).map((k) => {
        const side = sides[k];
        return (
          <dl key={k} className="rounded-ctl bg-surface-2 px-4 py-3 text-sm">
            <dt className="font-semibold">{pair.name(side.retailer)}</dt>
            <dd className="mt-2 grid grid-cols-3 gap-2 tabular-nums">
              {(['observed', 'counted', 'onlyHere'] as const).map((f) => (
                <span key={f} className="min-w-0">
                  <span className="block text-xs text-ink-2">{t(f)}</span>
                  <span className="block text-xl font-bold tracking-tight">
                    {formatCount(side[f], locale)}
                  </span>
                </span>
              ))}
            </dd>
            {side.reason && (
              <dd className="mt-2 text-xs text-ink-2">
                <Known t={tr} v={side.reason} />
              </dd>
            )}
          </dl>
        );
      })}
    </div>
  );
}
