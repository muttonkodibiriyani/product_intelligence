'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { formatCount, formatDate } from '@/lib/format';
import { DatasetStatus } from '../dataset-status';
import { ErrorNotice } from '../error-notice';
import { Card, CardGrid } from '../ui/card';
import { EnvNotes } from '../ui/env-notes';
import { Known } from '../ui/known';
import { useRetailerName } from '../use-meta';
import { KpiWidget } from '../widgets/kpis';
import { TopDiscountsWidget } from '../widgets/top-discounts';
import type { Summary } from '@/lib/api/summary';
import { useSummaryData } from '../widgets/use-summary';
import { BRANDS_TOP } from '../widgets/constants';
import {
  brandShare,
  categoryNodes,
  ladderRows,
  pct,
  promotions,
  promotionsHref,
  WITHHELD_REASONS,
} from '../widgets/model';

// The charts (and ECharts with them) load after the page: the KPIs and the table come first.
const charts = () => import('../widgets/charts');
const LadderWidget = dynamic(() => charts().then((m) => m.LadderWidget), { ssr: false });
const PromoDepthWidget = dynamic(() => charts().then((m) => m.PromoDepthWidget), { ssr: false });
const BrandPriceWidget = dynamic(() => charts().then((m) => m.BrandPriceWidget), { ssr: false });
const CategoryMixWidget = dynamic(() => charts().then((m) => m.CategoryMixWidget), { ssr: false });
const PriceHistWidget = dynamic(() => charts().then((m) => m.PriceHistWidget), { ssr: false });
const BrandShareWidget = dynamic(() => charts().then((m) => m.BrandShareWidget), { ssr: false });
const RatingPriceWidget = dynamic(() => charts().then((m) => m.RatingPriceWidget), { ssr: false });

type View = 'overview' | 'compare';

/** The landing: the current snapshot at a glance, and the comparison layout waiting for data. */
export function Landing() {
  const t = useTranslations('home.landing');
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const view: View = sp.get('view') === 'compare' ? 'compare' : 'overview';
  const go = (v: View) =>
    router.replace(v === 'compare' ? `${pathname}?view=compare` : pathname, { scroll: false });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-bold tracking-tight">{t('overview')}</h1>
          <Subtitle />
        </div>
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
      </div>
      <div role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`}>
        {view === 'overview' ? <Overview /> : <ComparePreview />}
      </div>
    </div>
  );
}

function Subtitle() {
  const t = useTranslations('home.landing');
  const locale = useLocale();
  const name = useRetailerName();
  const s = useSummaryData();
  if (s.kind !== 'ready') return null;
  return (
    <p className="mt-1 text-sm text-ink-2">
      {t('subtitle', {
        retailer: name(s.data.retailer),
        date: formatDate(s.data.asOf, locale),
      })}
    </p>
  );
}

function Overview() {
  const tw = useTranslations('widgets');
  const tt = useTranslations('widgets.top');
  const tc = useTranslations('card');
  const locale = useLocale();
  const s = useSummaryData();

  if (s.kind === 'error') return <ErrorNotice error={s.error} onRetry={s.retry} />;
  if (s.kind === 'loading')
    return (
      <p role="status" aria-busy className="text-ink-2">
        {tc('loading')}
      </p>
    );
  if (s.kind === 'empty')
    return (
      <>
        <EnvNotes env={s.env} />
        <Dataset />
      </>
    );

  const { data, currency } = s;
  const p = { currency, locale };
  const card = (key: string) => ({ title: tw(`${key}.title`), id: `w-${key}` });
  // Only widgets the snapshot can fill: the landing never shows an empty card. Promotion widgets
  // need regular prices; until /summary reports them they wait on the Compare tab as previews.
  const promo = promotions(data);
  // Null sections are withheld (/summary says why); locals keep them narrowed inside the cards.
  const { ladder, brandPrice, priceHist, ratingPrice, categoryMix, priced } = data;
  const half = [
    ladder &&
      ladderRows(ladder).length > 0 &&
      ((span: 6 | 12) => (
        <Card key="ladder" span={span} {...card('ladder')} question={tw('ladder.question')}>
          <LadderWidget data={ladder} {...p} />
        </Card>
      )),
    brandPrice &&
      brandPrice.length > 0 &&
      ((span: 6 | 12) => (
        <Card
          key="brands"
          span={span}
          {...card('brands')}
          question={tw('brands.question', { n: Math.min(BRANDS_TOP, brandPrice.length) })}
        >
          <BrandPriceWidget data={brandPrice} {...p} />
        </Card>
      )),
    priceHist &&
      priceHist.counts.some((c) => c > 0) &&
      ((span: 6 | 12) => (
        <Card key="hist" span={span} {...card('hist')} question={tw('hist.question')}>
          <PriceHistWidget data={priceHist} {...p} />
        </Card>
      )),
    ratingPrice &&
      ratingPrice.points.length > 0 &&
      ((span: 6 | 12) => (
        <Card key="rating" span={span} {...card('rating')} question={tw('rating.question')}>
          <RatingPriceWidget data={ratingPrice} {...p} />
          <RatingNote data={ratingPrice} />
        </Card>
      )),
    categoryMix &&
      categoryNodes(categoryMix).length > 0 &&
      ((span: 6 | 12) => (
        <Card key="mix" span={span} {...card('mix')} question={tw('mix.question')}>
          <CategoryMixWidget data={categoryMix} {...p} />
        </Card>
      )),
    brandPrice &&
      priced &&
      brandShare(brandPrice, priced).length > 0 &&
      ((span: 6 | 12) => (
        <Card key="share" span={span} {...card('share')} question={tw('share.question')}>
          <BrandShareWidget data={brandPrice} priced={priced} {...p} />
        </Card>
      )),
    promo.measured &&
      promo.depth.category.length > 0 &&
      ((span: 6 | 12) => (
        <Card key="promo" span={span} {...card('promo')} question={tw('promo.question')}>
          <PromoDepthWidget data={promo.depth} {...p} />
        </Card>
      )),
  ].filter((c): c is (span: 6 | 12) => React.JSX.Element => typeof c === 'function');

  return (
    <div className="space-y-6">
      <EnvNotes env={s.env} />
      <WithheldNote withheld={data.withheld} />
      <KpiWidget data={data} locale={locale} />
      <p className="text-xs text-ink-2">{tw('drill')}</p>
      <CardGrid>
        {/* Two per row; an odd one out takes the full row. */}
        {half.map((card, i) => card(i === half.length - 1 && half.length % 2 === 1 ? 12 : 6))}
        {promo.measured && promo.top.length > 0 && (
          <Card
            {...card('top')}
            question={tt('question')}
            flush
            tools={
              <Link href={promotionsHref(locale, {})} className="btn text-sm focus-visible:outline-2">
                {tt('all')}
              </Link>
            }
          >
            <TopDiscountsWidget data={promo.top} locale={locale} retailer={data.retailer} />
          </Card>
        )}
      </CardGrid>
      <Dataset />
    </div>
  );
}

/**
 * Why price or rating cards are missing: /summary's own reason per withheld section. Promotions
 * are left out; they wait on the Compare tab with their reason as the caption.
 */
function WithheldNote({ withheld }: { withheld: Summary['withheld'] }) {
  const t = useTranslations('widgets.withheld');
  const tr = useTranslations('reasons');
  const shown = withheld.filter(
    (w): w is Summary['withheld'][number] & { section: 'prices' | 'ratings' } =>
      w.section === 'prices' || w.section === 'ratings',
  );
  if (shown.length === 0) return null;
  return (
    <div role="note" className="space-y-1 panel px-4 py-3 text-sm">
      {shown.map((w) => (
        <p key={w.section}>
          {t(w.section)} <Known t={tr} v={w.reason} />
        </p>
      ))}
    </div>
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

function Dataset() {
  return (
    <section id="dataset" className="panel scroll-mt-6 px-5 py-4">
      <DatasetStatus nested />
    </section>
  );
}

/** Comparison cards: their layout only, until a second retailer or a second day exists. */
function ComparePreview() {
  const t = useTranslations('home.landing');
  const locale = useLocale();
  const tw = useTranslations('widgets');
  const s = useSummaryData();
  const cards: [string, string, string][] = [
    [t('indexTitle'), t('indexQuestion'), t('indexReason')],
    [t('gapTitle'), t('gapQuestion'), t('gapReason')],
    [t('overlapTitle'), t('overlapQuestion'), t('overlapReason')],
  ];
  // Promotion widgets join the previews while the snapshot has no regular prices.
  const promo = s.kind === 'ready' ? promotions(s.data) : null;
  if (promo && !promo.measured) {
    // The caption is /summary's own reason for withholding them.
    const why = (WITHHELD_REASONS as readonly string[]).includes(promo.reason)
      ? t(`withheld.${promo.reason as (typeof WITHHELD_REASONS)[number]}`)
      : t('withheld.other');
    cards.push([tw('promo.title'), tw('promo.question'), why], [tw('top.title'), tw('top.question'), why]);
  }
  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm text-ink-2">{t('compareNote')}</p>
      <CardGrid>
        {cards.map(([title, q, reason], i) => (
          <Card
            key={i}
            id={`preview-${i}`}
            title={title}
            question={q}
            span={i === 0 ? 12 : 6}
            state="preview"
            reason={reason}
            tools={
              i === 0 ? (
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
