'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState, type ReactNode } from 'react';
import type { Envelope, Schemas } from '@/lib/api/types';
import { hasComparePair, parseCompare, toCompareSearch, type CompareState } from '@/lib/compare';
import { formatCount, formatDate } from '@/lib/format';
import {
  allObservedOut,
  barPct,
  BRANDS_SHOWN,
  deepestUndercut,
  forPair,
  INSIGHTS_API,
  insightsServed,
  gapScale,
  POLICY_ORDER,
  policyColumns,
  sizesInOrder,
  TRAPS_SHOWN,
  type Insights,
  type Ladder,
  type Stockouts,
} from '@/lib/insights';
import { navHref } from '@/lib/nav';
import { listedItems, notMeasured } from '@/lib/promotions';
import { PairPicker } from '../compare/pair-picker';
import { useAuth } from '../auth-provider';
import { ApiError } from '@/lib/api/client';
import { ErrorNotice } from '../error-notice';
import { productHref } from '../explore/product-table';
import { Card, CardGrid } from '../ui/card';
import { Known } from '../ui/known';
import { Money, Pct } from '../ui/money';
import { PageHeader } from '../ui/page-header';
import { RetailerDot } from '../ui/retailer-dot';
import { Loading } from '../ui/skeleton';
import { Tip } from '../ui/tip';
import { useMeta, useRetailerName } from '../use-meta';
import { activeRetailers, compareHref, exploreHref } from '../widgets/model';

/** The API's suppression floor (pi_metrics MIN_COHORT), quoted in the method tips. */
const MIN = 5;

/** A signed percentage as plain text for a sentence, isolated so it reads left to right in Arabic. */
const pctText = (v: string) => `⁦${v.startsWith('-') || Number(v) === 0 ? '' : '+'}${v}%⁩`;

/**
 * Insights: the decisions the latest data supports, one card each, in the order the coordinator
 * set (task 01a102f2). Every card is one headline, one chart, the action, and the method in a
 * tooltip; its evidence (Compare or Products, then the product) is two clicks away. Numbers come
 * only from /insights, /compare and /assortment-gaps. Cross-shop prices count reviewed exact
 * matches only; until there are some, the cards say so and show no number. Stock-outs at a
 * partly crawled shop are counts of observed listings, never a share, and shops are not ranked.
 */
export function InsightsView() {
  const t = useTranslations('insights');
  const ts = useTranslations('state');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { api } = useAuth();
  const meta = useMeta();
  const active = useMemo(() => activeRetailers(meta.data?.data), [meta.data]);

  const search = sp.toString();
  const parsed = useMemo(() => parseCompare(new URLSearchParams(search)), [search]);
  const [pending, setPending] = useState<{ at: string; state: CompareState } | null>(null);
  const picked = pending?.at === search ? pending.state : parsed;
  // Until a pair is picked, the first two shops the dataset collects.
  const state: CompareState =
    !hasComparePair(picked) && active.length >= 2
      ? { ...picked, base: active[0]!, other: active[1]! }
      : picked;
  const fixed = active.length === 2 && active.includes(state.base) && active.includes(state.other);
  const update = (next: Partial<CompareState>) => {
    const target = { ...state, ...next };
    setPending({ at: search, state: target });
    router.push(pathname + toCompareSearch(target), { scroll: false });
  };
  // An API older than INSIGHTS_API has no /insights: say so, and ask it nothing.
  const served = insightsServed(meta.data);
  const ready = hasComparePair(state) && served === true;
  const retailers = `${state.base},${state.other}`;

  const q = useQuery({
    queryKey: ['insights', retailers],
    queryFn: ({ signal }) => api!.get('/api/v1/insights', { query: { retailers }, signal }),
    enabled: !!api && ready,
  });
  const evidence = q.data?.data;
  const pricingReady = evidence?.pricing.status === 'ok' && evidence.pricing.n > 0;
  const summary = useQuery({
    queryKey: ['compare', 'insights', retailers],
    // The summary is computed over the full cohort regardless of the row limit. One evidence row
    // is enough here; the Compare link opens the full list when the user asks for it.
    queryFn: ({ signal }) => api!.get('/api/v1/compare', { query: { retailers, limit: 1 }, signal }),
    // No reviewed exact pairs means /compare can add only another withheld card. Do not ask for it.
    enabled: !!api && ready && pricingReady,
  });
  const gaps = useQuery({
    queryKey: ['assortment-gaps', 'insights', retailers],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/assortment-gaps', {
        query: { presentAt: state.other, missingAt: state.base },
        signal,
      }),
    enabled: !!api && ready && !!evidence,
  });
  const promotions = useQuery({
    queryKey: ['promotions', 'insights', retailers],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/promotions', {
        query: { retailer: [state.base, state.other], limit: 4 },
        signal,
      }),
    // First render the evidence aggregate; the compact promotion proof is a secondary request.
    enabled: !!api && ready && !!evidence,
  });

  // A 404 from /insights means the route is not deployed whatever /meta says: the same honest
  // "not available yet", never an error card.
  const missing = q.error instanceof ApiError && q.error.status === 404;
  const env = q.data;
  return (
    <section aria-labelledby="insights-title" className="space-y-5">
      <PageHeader
        id="insights-title"
        title={t('title')}
        intro={t('intro')}
        asOf={env && ts('asOf', { date: formatDate(env.meta.cutoff, locale) })}
      />
      {served && !missing && <PairPicker state={state} update={update} fixed={fixed} grouping={false} />}
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
      ) : missing ? (
        <div role="note" className="panel px-5 py-6 text-sm text-ink-2">
          {t('unavailableRoute')}
        </div>
      ) : !ready ? (
        <div className="panel px-5 py-6 text-sm text-ink-2">{t('pickPair')}</div>
      ) : q.isError ? (
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      ) : !env ? (
        <Loading kind="table" rows={6}>
          {t('loading')}
        </Loading>
      ) : (
        <Cards
          env={env}
          summary={summary.data}
          gaps={gaps.data}
          gapsPending={gaps.isPending}
          gapsError={gaps.isError}
          promotions={promotions.data}
          promotionsPending={promotions.isPending}
          promotionsError={promotions.isError}
          base={state.base}
          other={state.other}
        />
      )}
    </section>
  );
}

type Pair = { base: string; other: string };

function Cards({
  env,
  summary,
  gaps,
  gapsPending,
  gapsError,
  promotions,
  promotionsPending,
  promotionsError,
  base,
  other,
}: Pair & {
  env: Envelope<Insights>;
  summary: Envelope<Schemas['Comparison']> | undefined;
  gaps: Envelope<Schemas['AssortmentGaps']> | undefined;
  gapsPending: boolean;
  gapsError: boolean;
  promotions: Envelope<Schemas['Promotions']> | undefined;
  promotionsPending: boolean;
  promotionsError: boolean;
}) {
  const t = useTranslations('insights');
  const data = env.data;
  const pair = { base, other };
  if (!data) return <ReasonCard title={t('title')} reason={env.reason} />;
  const stocks = forPair(data.stockouts, base, other);
  const ladders = forPair(data.ladders, base, other);
  const promoItems = promotions?.data
    ? listedItems(promotions.data).items.filter((item) => item.retailer === base || item.retailer === other)
    : [];
  const hasSizes = data.pricing.status === 'ok' && data.pricing.sizes.length > 0;
  const hasPolicy = data.pricing.status === 'ok' && data.pricing.brands.length > 0;
  const hasSpace = !!gaps?.data && gaps.status === 'ok' && gaps.data.total > 0;
  const hasPromos = promoItems.length > 0;
  const hasStock = stocks.some((row) => row.brands.length > 0);
  const hasTraps = ladders.some((row) => row.reason === null && row.steps > 0);
  const readyCount = [hasSizes, hasPolicy, hasSpace, hasPromos, hasStock, hasTraps].filter(Boolean).length;
  const pending = gapsPending || promotionsPending;
  return (
    <div className="space-y-5">
      <Readiness ready={readyCount} pending={pending} unreviewed={data.pricing.unreviewed} />
      <ReportMethod pricing={data.pricing} stocks={stocks} ladders={ladders} />
      <FindingToc
        items={
          [
            hasStock && ['stock', t('stock.title')],
            hasTraps && ['traps', t('traps.title')],
            hasSizes && ['size', t('size.title')],
            hasPolicy && ['policy', t('policy.title')],
            hasPromos && ['promo', t('promo.title')],
            hasSpace && ['space', t('space.title')],
          ].filter(Boolean) as [string, string][]
        }
      />
      {data.pricing.status === 'ok' && data.pricing.n > 0 && (
        <Positioning env={summary} pricing={data.pricing} {...pair} />
      )}
      <CardGrid>
        {/* Primary evidence never moves while the smaller supporting requests settle. */}
        {hasStock && <StockCard rows={stocks} cutoff={env.meta.cutoff} />}
        {hasTraps && <TrapCard ladders={ladders} held={data.heldOutPct} />}
        {hasSizes && <SizeCard pricing={data.pricing} {...pair} />}
        {hasPolicy && <PolicyCard pricing={data.pricing} share={data.policySharePct} {...pair} />}
        {promotionsPending ? (
          <Card title={t('promo.title')} span={6} state="loading" skeleton="lines" />
        ) : (
          hasPromos && <PromoCard items={promoItems} base={base} other={other} />
        )}
        {gapsPending ? (
          <Card title={t('space.title')} span={6} state="loading" skeleton="chart" />
        ) : (
          hasSpace && <WhiteSpaceCard env={gaps} />
        )}
      </CardGrid>
      <Deferred
        pricing={data.pricing}
        base={base}
        other={other}
        gaps={gaps}
        gapsPending={gapsPending}
        gapsError={gapsError}
        promotions={promotions}
        promotionsPending={promotionsPending}
        promotionsError={promotionsError}
        stocks={stocks}
        ladders={ladders}
      />
      <More ladders={ladders} share={data.policySharePct} held={data.heldOutPct} />
      <TestedNotPromoted />
    </div>
  );
}

/** Analyses intentionally withheld from the ranked report until their evidence is publishable. */
function TestedNotPromoted() {
  const t = useTranslations('insights.report');
  return (
    <section aria-labelledby="tested-not-promoted" className="panel px-5 py-4">
      <h2 id="tested-not-promoted" className="text-base font-semibold">
        {t('testedTitle')}
      </h2>
      <p className="mt-1 text-sm text-ink-2">{t('testedIntro')}</p>
      <ul className="mt-3 grid gap-2 text-sm text-ink-2 sm:grid-cols-2">
        {(['history', 'gwp', 'rating'] as const).map((key) => (
          <li key={key} className="rounded-ctl bg-surface-2 px-3 py-2">
            <span className="font-medium text-ink">{t(`tested.${key}.title`)}</span>
            <span className="ms-1">{t(`tested.${key}.body`)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FindingToc({ items }: { items: [string, string][] }) {
  const t = useTranslations('insights.report');
  if (items.length === 0) return null;
  return (
    <nav aria-label={t('toc')} className="panel px-5 py-4">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-2">{t('toc')}</p>
      <ol className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {items.map(([id, label], i) => (
          <li key={id}>
            <a
              className="flex items-baseline gap-2 text-sm underline-offset-2 hover:underline"
              href={`#finding-${id}`}
            >
              <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ink text-[11px] font-semibold text-surface">
                {i + 1}
              </span>
              {label}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function ReportMethod({
  pricing,
  stocks,
  ladders,
}: {
  pricing: Insights['pricing'];
  stocks: Stockouts[];
  ladders: Ladder[];
}) {
  const t = useTranslations('insights.report');
  const meta = useMeta().data?.data;
  const retailerIds = new Set([...stocks.map((s) => s.retailer), ...ladders.map((l) => l.retailer)]);
  const metadataPartial = meta?.retailers.some((r) => retailerIds.has(r.id) && r.status !== 'supported');
  const partial =
    metadataPartial ??
    (stocks.some((s) => s.reason === null && s.brands.length > 0) ||
      ladders.some((l) => l.reason === 'cohort_too_small'));
  return (
    <details className="panel px-5 py-3 text-sm text-ink-2">
      <summary className="cursor-pointer font-medium text-ink">{t('method')}</summary>
      <dl className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-[auto_1fr]">
        <dt className="text-xs font-semibold uppercase tracking-wide">{t('n')}</dt>
        <dd>{pricing.n}</dd>
        <dt className="text-xs font-semibold uppercase tracking-wide">{t('cohort')}</dt>
        <dd>{t('cohortValue')}</dd>
        <dt className="text-xs font-semibold uppercase tracking-wide">{t('matches')}</dt>
        <dd>{pricing.unreviewed > 0 ? t('unreviewed', { n: pricing.unreviewed }) : t('reviewed')}</dd>
        <dt className="text-xs font-semibold uppercase tracking-wide">{t('coverage')}</dt>
        <dd>{partial ? t('partial') : t('complete')}</dd>
      </dl>
    </details>
  );
}

/** Lead with what the snapshot can answer; the unavailable analyses are one explanation below. */
function Readiness({ ready, pending, unreviewed }: { ready: number; pending: boolean; unreviewed: number }) {
  const t = useTranslations('insights.readiness');
  const locale = useLocale();
  return (
    <section aria-labelledby="readiness-title" className="panel overflow-hidden">
      <div className="bg-gradient-to-br from-accent/[0.10] via-surface to-series-b/[0.08] px-5 py-5 sm:px-6">
        <p className="text-[11px] font-semibold tracking-[0.12em] text-accent uppercase">{t('eyebrow')}</p>
        <h2 id="readiness-title" className="mt-1 text-xl font-bold tracking-tight">
          {t('title', { n: ready, count: formatCount(ready, locale) })}
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">{t('body')}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className="rounded-full bg-surface px-2.5 py-1 font-medium shadow-sm">
            {t('ready', { n: ready, count: formatCount(ready, locale) })}
          </span>
          {unreviewed > 0 && (
            <span className="rounded-full bg-butter px-2.5 py-1 font-medium text-butter-ink">
              {t('unreviewed', { n: unreviewed, count: formatCount(unreviewed, locale) })}
            </span>
          )}
          {pending && (
            <span className="rounded-full bg-surface-2 px-2.5 py-1 text-ink-2">{t('checking')}</span>
          )}
        </div>
      </div>
    </section>
  );
}

/** A card's "so what" line and its evidence link, under the chart. */
function Foot({ action, href, label }: { action: string; href?: string; label?: string }) {
  const t = useTranslations('insights');
  return (
    <div className="mt-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-line pt-3 text-sm">
      <p>
        <b className="me-1.5 font-semibold">{t('soWhat')}</b>
        {action}
      </p>
      {href && (
        <Link href={href} className="text-accent underline-offset-2 hover:underline focus-visible:outline-2">
          {label ?? t('evidence')}
        </Link>
      )}
    </div>
  );
}

/** The cohort line under a card's title: the count behind it, with the method in the tooltip. */
function Meta({ children, tip }: { children: ReactNode; tip: ReactNode }) {
  return (
    <Tip text={tip}>
      <span className="underline decoration-dotted underline-offset-2">{children}</span>
    </Tip>
  );
}

function ReasonCard({
  title,
  reason,
  span = 12,
}: {
  title: string;
  reason: string | null | undefined;
  span?: 6 | 12;
}) {
  const tr = useTranslations('reasons');
  return (
    <Card title={title} span={span} state="empty" reason={reason ? <Known t={tr} v={reason} /> : undefined} />
  );
}

/** The label every cross-shop number keeps while some of the pair's matches are only proposed. */
function Unreviewed({ n }: { n: number }) {
  const t = useTranslations('insights');
  if (n === 0) return null;
  return (
    <span className="ms-2 rounded-full bg-butter px-2 py-0.5 text-xs font-medium text-butter-ink">
      {t('unreviewed', { n })}
    </span>
  );
}

/** Header strip: who is cheaper on how many counted pairs, as one stacked bar. */
function Positioning({
  env,
  pricing,
  base,
  other,
}: Pair & { env: Envelope<Schemas['Comparison']> | undefined; pricing: Insights['pricing'] }) {
  const t = useTranslations('insights.positioning');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const s = env?.data?.summary;
  if (!env) return <div className="panel h-16 animate-pulse" aria-hidden />;
  if (!s || s.n === 0)
    return (
      <div role="note" className="panel px-5 py-3 text-sm">
        <b className="me-2 font-semibold">{t('title')}</b>
        {pricing.reason ? <Known t={tr} v={pricing.reason} /> : t('none')}
        <Unreviewed n={pricing.unreviewed} />
      </div>
    );
  const atOther = s.cheaperCounts[other] ?? 0;
  const atBase = s.cheaperCounts[base] ?? 0;
  const parts = [
    { id: other, n: atOther, cls: 'bg-series-b' },
    { id: 'equal', n: s.equalCount, cls: 'bg-line-2' },
    { id: base, n: atBase, cls: 'bg-series-a' },
  ];
  return (
    <div className="panel px-5 py-3">
      <p className="text-sm">
        <b className="me-2 font-semibold">{t('title')}</b>
        {t('line', {
          shop: name(other),
          k: formatCount(atOther, locale),
          n: formatCount(s.n, locale),
          equal: formatCount(s.equalCount, locale),
          gap: pctText(s.medianGapPct),
        })}
        <Unreviewed n={pricing.unreviewed} />
      </p>
      <Tip text={t('tip', { base: name(base), other: name(other) })} className="mt-2 block">
        <div className="flex h-2.5 w-full overflow-hidden rounded-full" role="img" aria-label={t('bar')}>
          {parts.map((p) =>
            p.n > 0 ? <span key={p.id} className={p.cls} style={{ width: `${(p.n / s.n) * 100}%` }} /> : null,
          )}
        </div>
      </Tip>
    </div>
  );
}

/** 1. Gap by size: a diverging bar per size, the other shop's undercut to the left of zero. */
function SizeCard({ pricing, base, other }: Pair & { pricing: Insights['pricing'] }) {
  const t = useTranslations('insights.size');
  const locale = useLocale();
  const name = useRetailerName();
  if (pricing.status !== 'ok' || pricing.sizes.length === 0)
    return <ReasonCard title={t('title')} reason={pricing.reason ?? 'cohort_too_small'} span={6} />;
  const sizes = sizesInOrder(pricing.sizes);
  const max = gapScale(sizes.map((s) => s.medianGapPct));
  const deep = deepestUndercut(sizes);
  return (
    <Card
      id="finding-size"
      title={t('title')}
      span={6}
      question={
        deep
          ? t('headline', {
              shop: name(other),
              size: `${deep.value} ${deep.unit}`,
              gap: pctText(deep.medianGapPct),
              n: formatCount(deep.n, locale),
            })
          : t('headlineNone', { shop: name(other) })
      }
      meta={
        <Meta
          tip={t('tip', { base: name(base), other: name(other), min: MIN, hidden: pricing.suppressedSizes })}
        >
          {t('meta', { n: formatCount(pricing.n, locale) })}
        </Meta>
      }
    >
      <ul className="space-y-1.5" aria-label={t('title')}>
        {sizes.map((s) => {
          const w = barPct(s.medianGapPct, max);
          const left = Number(s.medianGapPct) < 0;
          return (
            <li
              key={`${s.value}${s.unit}`}
              className="grid grid-cols-[4.5rem_1fr_1fr_4rem] items-center gap-2 text-sm"
            >
              <span className="tabular-nums">
                {s.value} {s.unit}
              </span>
              <span className="flex h-3 justify-end">
                {left && <span className="rounded-s-sm bg-series-b" style={{ width: `${w}%` }} />}
              </span>
              <span className="flex h-3 border-s border-ink-2">
                {!left && <span className="rounded-e-sm bg-series-a" style={{ width: `${w}%` }} />}
              </span>
              <Tip
                text={t('row', { n: s.n, other: s.otherCheaper, equal: s.equal, base: s.baseCheaper })}
                at="end"
              >
                <span className="text-end">
                  <Pct v={s.medianGapPct} />
                </span>
              </Tip>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 grid grid-cols-[4.5rem_1fr_1fr_4rem] gap-2 text-xs text-ink-2">
        <span />
        <span className="text-end">{t('cheaperAt', { shop: name(other) })}</span>
        <span>{t('cheaperAt', { shop: name(base) })}</span>
      </p>
      <Foot action={t('action')} href={compareHref(locale, { base, other })} />
    </Card>
  );
}

/** 2. Brand price policy: brands in three columns by where their counted pairs fall. */
function PolicyCard({ pricing, share, base, other }: Pair & { pricing: Insights['pricing']; share: string }) {
  const t = useTranslations('insights.policy');
  const locale = useLocale();
  const name = useRetailerName();
  if (pricing.status !== 'ok' || pricing.brands.length === 0)
    return <ReasonCard title={t('title')} reason={pricing.reason ?? 'cohort_too_small'} span={6} />;
  const cols = policyColumns(pricing.brands);
  const head = {
    other_cheaper: t('colCheaper', { shop: name(other) }),
    parity: t('colParity'),
    base_cheaper: t('colCheaper', { shop: name(base) }),
    mixed: '',
  };
  return (
    <Card
      id="finding-policy"
      title={t('title')}
      span={6}
      question={t('headline', {
        k: cols.other_cheaper.length,
        shop: name(other),
        p: cols.parity.length,
      })}
      meta={
        <Meta tip={t('tip', { share, min: MIN })}>
          {t('meta', {
            mixed: cols.mixed.length,
            hidden: pricing.suppressedBrands,
          })}
        </Meta>
      }
    >
      <div className="grid grid-cols-3 gap-3 text-sm">
        {POLICY_ORDER.map((p) => (
          <div key={p} className="min-w-0">
            <h3 className="mb-1.5 text-xs font-medium text-ink-2">{head[p]}</h3>
            <ul className="space-y-1">
              {cols[p].slice(0, BRANDS_SHOWN).map((b) => (
                <li key={b.brand} className="flex items-baseline justify-between gap-2">
                  <Link
                    href={compareHref(locale, { base, other, brand: b.brand })}
                    className="truncate underline-offset-2 hover:underline focus-visible:outline-2"
                  >
                    {b.brand}
                  </Link>
                  <Tip
                    text={t('row', { n: b.n, other: b.otherCheaper, equal: b.equal, base: b.baseCheaper })}
                    at="end"
                  >
                    <span className="text-xs">
                      <Pct v={b.medianGapPct} />
                    </span>
                  </Tip>
                </li>
              ))}
            </ul>
            {cols[p].length > BRANDS_SHOWN && (
              <p className="mt-1 text-xs text-ink-2">{t('more', { n: cols[p].length - BRANDS_SHOWN })}</p>
            )}
          </div>
        ))}
      </div>
      <Foot action={t('action')} href={compareHref(locale, { base, other })} />
    </Card>
  );
}

/** 3. White space: what the other shop lists that the base shop has no match for, by brand. */
function WhiteSpaceCard({ env }: { env: Envelope<Schemas['AssortmentGaps']> | undefined }) {
  const t = useTranslations('insights.space');
  const locale = useLocale();
  const name = useRetailerName();
  if (!env) return <Card title={t('title')} span={6} state="loading" />;
  const d = env.data;
  if (!d || env.status !== 'ok' || d.total === 0)
    return <ReasonCard title={t('title')} reason={env.reason ?? 'cohort_too_small'} span={6} />;
  // "Missing" only when every row is a confirmed absence; any unreviewed or omitted row makes
  // the card use the honest "no reviewed match" wording.
  const missing =
    d.items.length === d.total && d.items.length > 0 && d.items.every((i) => i.label === 'missing');
  const top = d.byBrand.slice(0, BRANDS_SHOWN);
  const max = Math.max(1, ...top.map((b) => b.count));
  return (
    <Card
      id="finding-space"
      title={t('title')}
      span={6}
      question={t(missing ? 'headlineMissing' : 'headlineUnmatched', {
        n: d.total,
        count: formatCount(d.total, locale),
        present: name(d.presentAt),
        absent: name(d.missingAt),
      })}
      meta={<Meta tip={t('tip', { absent: name(d.missingAt) })}>{t('meta')}</Meta>}
    >
      <ul className="space-y-1.5 text-sm">
        {top.map((b) => (
          <li key={b.brand} className="grid grid-cols-[minmax(0,10rem)_1fr_3rem] items-center gap-2">
            <Link
              href={exploreHref(locale, { brand: [b.brand], retailer: [d.presentAt] })}
              className="truncate underline-offset-2 hover:underline focus-visible:outline-2"
            >
              {b.brand}
            </Link>
            <span className="h-3 rounded-e-sm bg-series-b" style={{ width: `${(b.count / max) * 100}%` }} />
            <span className="text-end tabular-nums">{formatCount(b.count, locale)}</span>
          </li>
        ))}
      </ul>
      <Foot action={t('action')} />
    </Card>
  );
}

/** 4. The deepest observed discounts for the pair, from API 1.18's promotion rows. */
function PromoCard({ items, base, other }: Pair & { items: Schemas['PromoItem'][] }) {
  const t = useTranslations('insights.promo');
  const locale = useLocale();
  const name = useRetailerName();
  const shown = items
    .filter((item) => item.retailer === base || item.retailer === other)
    .sort((a, b) => Number(b.depthPct) - Number(a.depthPct) || a.id.localeCompare(b.id))
    .slice(0, 4);
  const deepest = shown[0]!;
  return (
    <Card
      id="finding-promo"
      title={t('title')}
      span={6}
      question={t('headline', {
        product: deepest.name,
        shop: name(deepest.retailer),
        pct: deepest.depthPct,
      })}
      meta={t('meta', { n: shown.length, count: formatCount(shown.length, locale) })}
    >
      <ol className="divide-y divide-line text-sm">
        {shown.map((item, index) => (
          <li key={`${item.id}:${item.retailer}`} className="flex items-center gap-3 py-2 first:pt-0">
            <span className="w-5 shrink-0 text-xs font-semibold text-ink-3 tabular-nums">
              <bdi dir="ltr">#{formatCount(index + 1, locale)}</bdi>
            </span>
            <span className="min-w-0 flex-1">
              <Link
                href={`${productHref(locale, item.id)}#evidence`}
                className="block truncate font-medium underline-offset-2 hover:underline focus-visible:outline-2"
                dir="auto"
              >
                {item.name}
              </Link>
              <span className="flex items-center gap-1.5 text-xs text-ink-2">
                <RetailerDot id={item.retailer} index={index} />
                <span dir="auto">{name(item.retailer)}</span>
              </span>
            </span>
            <span className="text-end">
              <span className="verdict verdict-good block">
                <bdi dir="ltr">−{item.depthPct}%</bdi>
              </span>
              {item.saved && (
                <span className="mt-0.5 block text-xs text-ink-2">
                  {t('saved')} <Money m={item.saved} locale={locale} />
                </span>
              )}
            </span>
          </li>
        ))}
      </ol>
      <Foot action={t('action')} href={navHref('promotions', locale)} label={t('open')} />
    </Card>
  );
}

/** 5. Brand stock-outs: counts of observed listings per shop, side by side, never a share. */
function StockCard({ rows, cutoff }: { rows: Stockouts[]; cutoff: string }) {
  const t = useTranslations('insights.stock');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const meta = useMeta().data?.data;
  const crawl = (id: string) =>
    meta?.retailers.find((r) => r.id === id)?.status === 'partial' ? 'partial' : 'other';
  const lead = rows.flatMap((r) =>
    r.brands.filter(allObservedOut).map((b) => ({ ...b, retailer: r.retailer })),
  )[0];
  if (rows.every((r) => r.brands.length === 0))
    return (
      <ReasonCard
        title={t('title')}
        reason={rows.find((r) => r.reason)?.reason ?? 'cohort_too_small'}
        span={6}
      />
    );
  const max = Math.max(1, ...rows.flatMap((r) => r.brands.map((b) => b.observed)));
  return (
    <Card
      id="finding-stock"
      title={t('title')}
      span={6}
      question={
        lead
          ? t('headline', {
              brand: lead.brand,
              shop: name(lead.retailer),
              out: formatCount(lead.outOfStock, locale),
              observed: formatCount(lead.observed, locale),
              crawl: crawl(lead.retailer),
            })
          : t('headlineSome', { min: MIN })
      }
      meta={
        <Meta
          tip={t('tip', {
            date: formatDate(cutoff, locale),
            min: MIN,
            hidden: rows.reduce((n, r) => n + r.suppressed, 0),
          })}
        >
          {t('meta')}
        </Meta>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {rows.map((r, i) => (
          <div key={r.retailer} className="min-w-0">
            <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-2">
              <RetailerDot id={r.retailer} index={i} />
              {name(r.retailer)}
              {crawl(r.retailer) === 'partial' && (
                <span className="rounded-full bg-butter px-1.5 text-[11px] text-butter-ink">
                  {t('partial')}
                </span>
              )}
            </h3>
            {r.brands.length === 0 ? (
              <p className="text-sm text-ink-2">
                {r.reason ? <Known t={tr} v={r.reason} /> : t('none', { min: MIN })}
              </p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {r.brands.slice(0, BRANDS_SHOWN).map((b) => (
                  <li key={b.brand}>
                    <div className="flex items-baseline justify-between gap-2">
                      <Link
                        href={exploreHref(locale, { brand: [b.brand], retailer: [r.retailer] })}
                        className="truncate underline-offset-2 hover:underline focus-visible:outline-2"
                      >
                        {b.brand}
                      </Link>
                      <span className="text-xs tabular-nums text-ink-2">
                        {t('row', {
                          out: formatCount(b.outOfStock, locale),
                          observed: formatCount(b.observed, locale),
                        })}
                      </span>
                    </div>
                    {/* Two absolute counts on one scale; the drawing is never a share. */}
                    <span
                      className="relative mt-0.5 block h-1.5 rounded-full bg-line"
                      style={{ width: `${(b.observed / max) * 100}%` }}
                    >
                      <span
                        className="absolute inset-y-0 start-0 rounded-full bg-series-b"
                        style={{ width: `${(b.outOfStock / b.observed) * 100}%` }}
                      />
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {r.qualifying > BRANDS_SHOWN && (
              <p className="mt-1 text-xs text-ink-2">{t('more', { n: r.qualifying - BRANDS_SHOWN })}</p>
            )}
          </div>
        ))}
      </div>
      <Foot action={t('action')} />
    </Card>
  );
}

/** 6. Size traps: larger sizes that do not cost less per unit, per shop, with the products. */
function TrapCard({ ladders, held }: { ladders: Ladder[]; held: string }) {
  const t = useTranslations('insights.traps');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const measured = ladders.filter((l) => l.reason === null);
  if (measured.length === 0)
    return <ReasonCard title={t('title')} reason={ladders.find((l) => l.reason)?.reason} />;
  return (
    <Card
      id="finding-traps"
      title={t('title')}
      question={t('headline', {
        k: measured.reduce((n, l) => n + l.notCheaper, 0),
        n: formatCount(
          measured.reduce((n, l) => n + l.steps, 0),
          locale,
        ),
      })}
      meta={
        <Meta tip={t('tip', { held, heldOut: ladders.reduce((n, l) => n + l.heldOut, 0) })}>{t('meta')}</Meta>
      }
    >
      <div className="grid gap-5 md:grid-cols-2">
        {ladders.map((l, i) => (
          <div key={l.retailer} className="min-w-0">
            <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-2">
              <RetailerDot id={l.retailer} index={i} />
              {l.reason === null
                ? t('shop', { shop: name(l.retailer), k: l.notCheaper, n: formatCount(l.steps, locale) })
                : name(l.retailer)}
            </h3>
            {l.reason !== null ? (
              <p className="text-sm text-ink-2">
                <Known t={tr} v={l.reason} />
              </p>
            ) : (
              <ul className="divide-y divide-line text-sm">
                {l.exceptions.slice(0, TRAPS_SHOWN).map((s) => (
                  <li
                    key={`${s.smallerId}-${s.largerId}`}
                    className="flex items-baseline justify-between gap-3 py-1.5"
                  >
                    <span className="min-w-0">
                      <span className="block truncate">
                        {s.brand} · {s.name}
                      </span>
                      <span className="text-xs text-ink-2">
                        <Link
                          href={productHref(locale, s.smallerId)}
                          className="underline-offset-2 hover:underline"
                        >
                          {s.smallerValue} {s.unit} <Money m={s.smallerPrice} locale={locale} />
                        </Link>
                        {' → '}
                        <Link
                          href={productHref(locale, s.largerId)}
                          className="underline-offset-2 hover:underline"
                        >
                          {s.largerValue} {s.unit} <Money m={s.largerPrice} locale={locale} />
                        </Link>
                      </span>
                    </span>
                    <Tip text={t('perUnit', { unit: s.unit, basis: s.basis })} at="end">
                      <span className="text-xs font-medium text-rose-ink">
                        <Pct v={s.unitChangePct} />
                      </span>
                    </Tip>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <Foot action={t('action')} />
    </Card>
  );
}

/** Withheld analyses live in one disclosure instead of occupying most of the page as dead cards. */
function Deferred({
  pricing,
  base,
  other,
  gaps,
  gapsPending,
  gapsError,
  promotions,
  promotionsPending,
  promotionsError,
  stocks,
  ladders,
}: {
  pricing: Insights['pricing'];
  base: string;
  other: string;
  gaps: Envelope<Schemas['AssortmentGaps']> | undefined;
  gapsPending: boolean;
  gapsError: boolean;
  promotions: Envelope<Schemas['Promotions']> | undefined;
  promotionsPending: boolean;
  promotionsError: boolean;
  stocks: Stockouts[];
  ladders: Ladder[];
}) {
  const t = useTranslations('insights');
  const tr = useTranslations('reasons');
  const promoItems = promotions?.data
    ? listedItems(promotions.data).items.filter((item) => item.retailer === base || item.retailer === other)
    : [];
  const promoWhy = promotions ? notMeasured(promotions, null) : null;
  type DeferredRow = { title: string; reason?: string; message?: string };
  const candidates: Array<DeferredRow | null> = [
    pricing.status !== 'ok' || pricing.sizes.length === 0
      ? { title: t('size.title'), reason: pricing.reason ?? 'cohort_too_small' }
      : null,
    pricing.status !== 'ok' || pricing.brands.length === 0
      ? { title: t('policy.title'), reason: pricing.reason ?? 'cohort_too_small' }
      : null,
    !gapsPending && gapsError
      ? { title: t('space.title'), message: t('readiness.failed') }
      : !gapsPending && gaps?.status === 'ok' && gaps.data?.total === 0
        ? { title: t('space.title'), message: t('readiness.noneSpace') }
        : !gapsPending && (!gaps?.data || gaps.status !== 'ok')
          ? { title: t('space.title'), reason: gaps?.reason ?? 'cohort_too_small' }
          : null,
    !promotionsPending && promotionsError
      ? { title: t('promo.title'), message: t('readiness.failed') }
      : !promotionsPending && promoItems.length === 0 && promoWhy === null && promotions?.status === 'ok'
        ? { title: t('promo.title'), message: t('readiness.nonePromotions') }
        : !promotionsPending && promoItems.length === 0
          ? { title: t('promo.title'), reason: promoWhy ?? promotions?.reason ?? 'field_not_collected' }
          : null,
    stocks.every((row) => row.brands.length === 0)
      ? {
          title: t('stock.title'),
          reason: stocks.find((row) => row.reason)?.reason ?? 'cohort_too_small',
        }
      : null,
    !ladders.some((row) => row.reason === null && row.steps > 0)
      ? {
          title: t('traps.title'),
          reason: ladders.find((row) => row.reason)?.reason ?? 'cohort_too_small',
        }
      : null,
  ];
  const rows = candidates.filter((row): row is DeferredRow => row !== null);
  if (rows.length === 0) return null;
  return (
    <details className="panel px-5 py-4 text-sm">
      <summary className="cursor-pointer font-semibold focus-visible:outline-2">
        {t('readiness.deferred', { n: rows.length })}
      </summary>
      <p className="mt-2 text-ink-2">{t('readiness.deferredBody')}</p>
      <ul className="mt-3 grid gap-2 sm:grid-cols-2">
        {rows.map((row) => (
          <li key={row.title} className="rounded-ctl bg-surface-2 px-3 py-2">
            <b className="me-1.5 font-medium text-ink">{row.title}</b>
            <span className="text-ink-2">
              {row.message ?? (row.reason ? <Known t={tr} v={row.reason} /> : null)}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Secondary: the ladders' typical saving and how the page counts, folded away. */
function More({ ladders, share, held }: { ladders: Ladder[]; share: string; held: string }) {
  const t = useTranslations('insights.more');
  const locale = useLocale();
  const name = useRetailerName();
  return (
    <details className="panel px-5 py-3 text-sm">
      <summary className="cursor-pointer font-semibold">{t('title')}</summary>
      <ul className="mt-2 space-y-1">
        {ladders
          .filter((l) => l.medianSavingPct !== null)
          .map((l) => (
            <li key={l.retailer}>
              {t('saving', {
                shop: name(l.retailer),
                pct: `⁦${l.medianSavingPct}%⁩`,
                n: formatCount(l.steps, locale),
              })}
            </li>
          ))}
        <li className="text-ink-2">{t('method', { share, held, min: MIN })}</li>
        <li className="text-ink-2">{t('later')}</li>
      </ul>
    </details>
  );
}
