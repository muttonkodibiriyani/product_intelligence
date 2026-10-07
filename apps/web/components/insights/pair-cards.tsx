'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Envelope, Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import {
  barPct,
  BRANDS_SHOWN,
  deepestUndercut,
  gapScale,
  POLICY_ORDER,
  policyColumns,
  sizesInOrder,
  type Insights,
} from '@/lib/insights';
import { useAuth } from '../auth-provider';
import { Card, CardGrid } from '../ui/card';
import { Known } from '../ui/known';
import { Pct } from '../ui/money';
import { RetailerDot } from '../ui/retailer-dot';
import { Tip } from '../ui/tip';
import { useRetailerName } from '../use-meta';
import { compareHref, exploreHref } from '../widgets/model';

/** The API's suppression floor (pi_metrics MIN_COHORT), quoted in the method tips. */
const MIN = 5;

/** A signed percentage as plain text for a sentence, isolated so it reads left to right in Arabic. */
const pctText = (v: string) => `\u2066${v.startsWith('-') || Number(v) === 0 ? '' : '+'}${v}%\u2069`;

type Pair = { base: string; other: string };

export type PairCard = 'size' | 'policy' | 'space';
type Half = 6 | 12;

/** The pair's cards that have something to show, in page order. */
export function pairCards(sizes: boolean, brands: boolean, space: boolean): PairCard[] {
  return (['size', 'policy', 'space'] as const).filter((_, i) => [sizes, brands, space][i]);
}

/** Two to a row; an odd last card takes the whole row instead of leaving half of it empty. */
export const cardSpan = (shown: readonly PairCard[], c: PairCard): Half =>
  shown.length % 2 === 1 && shown.at(-1) === c ? 12 : 6;

/**
 * Cross-shop prices for one pair, shown only once the pair has reviewed exact matches: the price
 * position, the gap by size, brand price policy and the assortment white space. Numbers come from
 * /insights, /compare and /assortment-gaps; proposed matches are never counted.
 */
export function PairPrices({
  pricing,
  share,
  base,
  other,
}: Pair & { pricing: Insights['pricing']; share: string }) {
  const { api } = useAuth();
  const name = useRetailerName();
  const retailers = `${base},${other}`;
  const summary = useQuery({
    queryKey: ['compare', 'insights', retailers],
    // The summary is computed over the full cohort regardless of the row limit.
    queryFn: ({ signal }) => api!.get('/api/v1/compare', { query: { retailers, limit: 1 }, signal }),
    enabled: !!api,
  });
  const gaps = useQuery({
    queryKey: ['assortment-gaps', 'insights', retailers],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/assortment-gaps', { query: { presentAt: other, missingAt: base }, signal }),
    enabled: !!api,
  });
  const hasSpace = gaps.data?.status === 'ok' && (gaps.data.data?.total ?? 0) > 0;
  const shown = pairCards(pricing.sizes.length > 0, pricing.brands.length > 0, hasSpace);
  const span = (c: PairCard) => cardSpan(shown, c);
  return (
    <div className="space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <RetailerDot id={base} />
        {name(base)}
        <span className="text-ink-3">×</span>
        <RetailerDot id={other} index={1} />
        {name(other)}
      </h3>
      <Positioning env={summary.data} pricing={pricing} base={base} other={other} />
      <CardGrid>
        {shown.includes('size') && (
          <SizeCard pricing={pricing} base={base} other={other} span={span('size')} />
        )}
        {shown.includes('policy') && (
          <PolicyCard pricing={pricing} share={share} base={base} other={other} span={span('policy')} />
        )}
        {shown.includes('space') && (
          <WhiteSpaceCard env={gaps.data} span={span('space')} id={`finding-space-${base}-${other}`} />
        )}
      </CardGrid>
    </div>
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
    <Card
      level={4}
      title={title}
      span={span}
      state="empty"
      reason={reason ? <Known t={tr} v={reason} /> : undefined}
    />
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
function SizeCard({ pricing, base, other, span }: Pair & { pricing: Insights['pricing']; span: Half }) {
  const t = useTranslations('insights.size');
  const locale = useLocale();
  const name = useRetailerName();
  if (pricing.status !== 'ok' || pricing.sizes.length === 0)
    return <ReasonCard title={t('title')} reason={pricing.reason ?? 'cohort_too_small'} span={span} />;
  const sizes = sizesInOrder(pricing.sizes);
  const max = gapScale(sizes.map((s) => s.medianGapPct));
  const deep = deepestUndercut(sizes);
  return (
    <Card
      level={4}
      id="finding-size"
      title={t('title')}
      span={span}
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
function PolicyCard({
  pricing,
  share,
  base,
  other,
  span,
}: Pair & { pricing: Insights['pricing']; share: string; span: Half }) {
  const t = useTranslations('insights.policy');
  const locale = useLocale();
  const name = useRetailerName();
  if (pricing.status !== 'ok' || pricing.brands.length === 0)
    return <ReasonCard title={t('title')} reason={pricing.reason ?? 'cohort_too_small'} span={span} />;
  const cols = policyColumns(pricing.brands);
  const head = {
    other_cheaper: t('colCheaper', { shop: name(other) }),
    parity: t('colParity'),
    base_cheaper: t('colCheaper', { shop: name(base) }),
    mixed: '',
  };
  return (
    <Card
      level={4}
      id="finding-policy"
      title={t('title')}
      span={span}
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
            <h5 className="mb-1.5 text-xs font-medium text-ink-2">{head[p]}</h5>
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
// One per shop pair on the page, so the id (and the title it labels the section with) names the pair.
function WhiteSpaceCard({
  env,
  span,
  id,
}: {
  env: Envelope<Schemas['AssortmentGaps']> | undefined;
  span: Half;
  id: string;
}) {
  const t = useTranslations('insights.space');
  const locale = useLocale();
  const name = useRetailerName();
  if (!env) return <Card level={4} title={t('title')} span={span} state="loading" />;
  const d = env.data;
  if (!d || env.status !== 'ok' || d.total === 0)
    return <ReasonCard title={t('title')} reason={env.reason ?? 'cohort_too_small'} span={span} />;
  // "Missing" only when every row is a confirmed absence; any unreviewed or omitted row makes
  // the card use the honest "no reviewed match" wording.
  const missing =
    d.items.length === d.total && d.items.length > 0 && d.items.every((i) => i.label === 'missing');
  const top = d.byBrand.slice(0, BRANDS_SHOWN);
  const max = Math.max(1, ...top.map((b) => b.count));
  return (
    <Card
      level={4}
      id={id}
      title={t('title')}
      span={span}
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
