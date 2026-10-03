'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import { formatCount, loc } from '@/lib/format';
import type { Money as MoneyValue, Schemas } from '@/lib/api/types';
import { ErrorNotice } from '../error-notice';
import { Card } from '../ui/card';
import { Known } from '../ui/known';
import { Money, Pct } from '../ui/money';
import { AboutDataLink, PageHeader } from '../ui/page-header';
import { RetailerDot, retailerColor } from '../ui/retailer-dot';
import { Loading, Skeleton } from '../ui/skeleton';
import { Tip } from '../ui/tip';
import type { RetailerSummary } from '../widgets/kpis';
import { TopDiscountsWidget } from '../widgets/top-discounts';
import { useCategoryCompare } from '../widgets/use-category';
import { useCompareData, useRetailers, type PairState } from '../widgets/use-compare';
import { useSummaries } from '../widgets/use-summaries';
import { compareHref, promotions, promotionsHref } from '../widgets/model';
import { AsOf } from './as-of';
import { Band } from './band';
import { CategoryHeadToHead } from './category-head-to-head';
import { Insights } from './insights';
import { earlyExcluded, verdict } from './model';
import { useLaunchCounts, usePromoShares } from './use-overview-data';

type Pair = NonNullable<ReturnType<typeof useRetailers>['pair']>;
type Comparison = Schemas['Comparison'];

/**
 * The Overview: the band of tiles (each shop's catalogue, promotions, launches), one line on the
 * matched products, where each shop is cheaper by category, the matched basket, the charts that
 * dig into the data, and the deepest discounts. Every number comes from the API with the list it
 * was counted from one click away; the method notes live in tooltips and on the Dataset page.
 */
export function Landing() {
  const t = useTranslations('home.landing');
  const { ids, pair, loading, error } = useRetailers();
  const s = useSummaries(ids);
  return (
    <div className="space-y-6">
      <PageHeader
        title={t('overview')}
        asOf={s.rows.length > 0 ? <AsOf rows={s.rows} /> : undefined}
      />
      {error ? (
        <ErrorNotice error={error} />
      ) : loading ? (
        <Loading kind="chart">{t('loading')}</Loading>
      ) : (
        <Overview s={s} ids={ids} pair={pair} />
      )}
    </div>
  );
}

function Overview({
  s,
  ids,
  pair,
}: {
  s: ReturnType<typeof useSummaries>;
  ids: readonly string[];
  pair: Pair | null;
}) {
  const t = useTranslations('home.landing');
  const tc = useTranslations('card');
  // The pair's matched set and category medians; neither is asked for without a second retailer.
  const cmp = useCompareData(pair);
  const cat = useCategoryCompare(pair);
  const promo = usePromoShares();
  const launches = useLaunchCounts(ids);

  if (s.error && s.rows.length === 0) return <ErrorNotice error={s.error.error} onRetry={s.error.retry} />;
  if (s.loading && s.rows.length === 0) return <Loading kind="chart">{tc('loading')}</Loading>;
  // Nothing to report on (every retailer withheld or thin): one line, and the Dataset page says why.
  if (s.rows.length === 0)
    return (
      <p className="text-sm text-ink-2">
        {t('noRetailers')} <AboutDataLink />
      </p>
    );

  const matched = cmp.kind === 'ready' && cmp.data.summary !== null && cmp.data.summary.n > 0;
  return (
    <div className="space-y-6">
      <section id="kpi-band" aria-labelledby="kpi-band-title">
        <h2 id="kpi-band-title" className="sr-only">
          {t('numbers')}
        </h2>
        <Band rows={s.rows} promo={promo} launches={launches.shops} />
      </section>
      {pair && <Headline pair={pair} cmp={cmp} />}
      {pair && (
        <div className="grid grid-cols-12 items-start gap-5">
          <CategoryHeadToHead state={cat} pair={pair} span={matched ? 8 : 12} />
          {matched && <MatchedBasket pair={pair} data={cmp.data} />}
        </div>
      )}
      <Insights rows={s.rows} pair={pair} cat={cat} launches={launches} />
      <TopDiscounts rows={s.rows} />
    </div>
  );
}

/**
 * One line on the matched products, from /compare's own counts: who is cheaper on how many of
 * them, with the basket and the scope in the card beside the category table. It is an "early
 * read" only when the API's early_excluded caveat says items were left out. Without a matched
 * product yet: a quiet chip saying so, with the definition in its tooltip, and the link to compare.
 */
export function Headline({ pair, cmp }: { pair: Pair; cmp: PairState<Comparison> }) {
  const t = useTranslations('home.landing.headline');
  const tc = useTranslations('card');
  const locale = useLocale();
  if (cmp.kind === 'loading')
    return (
      <div className="px-1" aria-busy>
        <Skeleton kind="lines" rows={1} />
        <span role="status" className="sr-only">
          {tc('loading')}
        </span>
      </div>
    );
  if (cmp.kind === 'error') return <ErrorNotice error={cmp.error} onRetry={cmp.retry} />;
  const data = cmp.kind === 'ready' ? cmp.data : null;
  const s = data?.summary ?? null;
  if (!data || !s || s.n === 0)
    return <NoMatch pair={pair} data={data} reason={cmp.kind === 'empty' ? cmp.env?.reason : null} />;

  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const v = verdict(s, pair.base, pair.other);
  const leaderId = v.kind === 'lead' ? (v.leader === 'base' ? pair.base : pair.other) : null;
  const leader = leaderId ? pair.name(leaderId) : '';
  const trailer = v.kind === 'lead' ? (v.leader === 'base' ? other : base) : '';
  const early = cmp.kind === 'ready' ? earlyExcluded(cmp.env.caveats) : null;
  const tail =
    v.kind !== 'lead'
      ? ''
      : v.trailing > 0 && v.equal > 0
        ? t('tailBoth', { shop: trailer, trailing: v.trailing, equal: v.equal })
        : v.trailing > 0
          ? t('tailOther', { shop: trailer, trailing: v.trailing })
          : v.equal > 0
            ? t('tailEqual', { equal: v.equal })
            : '';
  return (
    <section className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-1" aria-labelledby="headline-title">
      {early && (
        <Tip text={loc(early.caveat, locale)}>
          <span className="pill bg-butter text-butter-ink">{t('early')}</span>
        </Tip>
      )}
      <h2 id="headline-title" className="text-base leading-snug font-semibold tracking-tight">
        {v.kind === 'allSame'
          ? t('allSame', { n: v.n, base, other })
          : v.kind === 'tie'
            ? t('tie', { k: v.k, n: v.n, base, other })
            : t.rich('lead', {
                shop: leader,
                k: v.k,
                n: v.n,
                b: (c) => <b style={{ color: retailerColor(leaderId!, v.leader === 'base' ? 0 : 1) }}>{c}</b>,
              })}
        {tail && ` ${tail}`}
      </h2>
      <Tip text={t('scope', { n: s.n, total: data.total })}>
        <span className="pill bg-surface-2 text-ink-2 tabular-nums">
          {t('of', { n: s.n, total: data.total })}
        </span>
      </Tip>
      <Link
        href={compareHref(locale, pair)}
        className="text-sm font-medium text-ink underline underline-offset-2 focus-visible:outline-2"
      >
        {t('see', { n: s.n })}
      </Link>
    </section>
  );
}

/**
 * No matched product yet: one quiet line. The chip says so (the definition and the API's reason
 * are in its tooltip), the counts the API did send sit beside it as chips, and the link opens
 * the comparison. A count the API did not send is left out, never shown as 0.
 */
export function NoMatch({
  pair,
  data,
  reason,
}: {
  pair: Pair;
  data: Comparison | null;
  reason?: string | null;
}) {
  const t = useTranslations('home.landing.match');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const sides = data ? [data.sides.base, data.sides.other] : null;
  return (
    <p id="no-match" className="flex flex-wrap items-center gap-2 px-1 text-xs text-ink-2">
      <Tip
        text={
          <>
            {t('why')}
            {reason && (
              <>
                {' '}
                <Known t={tr} v={reason} />
              </>
            )}
          </>
        }
      >
        <span className="pill bg-surface-2 font-medium text-ink">
          {data?.summary ? t('none', { n: data.summary.n }) : t('noneYet')}
        </span>
      </Tip>
      {sides &&
        [pair.base, pair.other].map((id, i) => (
          <Tip key={id} text={t('observed', { shop: pair.name(id), n: sides[i]!.observed })}>
            <span className="pill bg-surface-2 tabular-nums">
              <RetailerDot id={id} index={i} />
              {formatCount(sides[i]!.observed, locale)}
            </span>
          </Tip>
        ))}
      {data && (
        <Tip text={t('either', { n: data.total })}>
          <span className="pill bg-surface-2 tabular-nums">{t('total', { n: data.total })}</span>
        </Tip>
      )}
      <Link
        href={compareHref(locale, pair)}
        className="font-medium text-ink underline underline-offset-2 focus-visible:outline-2"
      >
        {t('open')}
      </Link>
    </p>
  );
}

/**
 * The matched basket head to head: what the same products cost at each shop, the API's median
 * gap, and a tally of who is cheaper how often, out of the products either shop sells.
 */
export function MatchedBasket({ pair, data }: { pair: Pair; data: Comparison }) {
  const t = useTranslations('widgets.basket');
  const locale = useLocale();
  const s = data.summary!;
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const a = s.cheaperCounts[pair.base] ?? 0;
  const b = s.cheaperCounts[pair.other] ?? 0;
  const e = s.equalCount;
  const seg = (n: number, bg: string) =>
    n > 0 ? <i className="block h-full" style={{ flex: `${n} 0 0`, background: bg }} /> : null;
  const basket = (id: string, index: 0 | 1, m: MoneyValue, gap?: ReactNode) => (
    <div className="min-w-0 px-5 py-3.5">
      <p className="flex items-center gap-1.5 text-xs text-ink-2">
        <RetailerDot id={id} index={index} />
        {t('basketOf', { shop: pair.name(id) })}
      </p>
      <p className="mt-0.5 text-[22px] leading-tight font-semibold tracking-tight tabular-nums @md:text-[26px]">
        <Money m={m} locale={locale} />
        {gap && (
          <small className="block text-[13px] font-normal tracking-normal text-ink-2 @md:ms-1.5 @md:inline">
            {gap}
          </small>
        )}
      </p>
    </div>
  );
  return (
    <Card
      id="w-basket"
      title={t('title')}
      span={4}
      flush
      tools={
        <Link href={compareHref(locale, pair)} className="btn text-sm focus-visible:outline-2">
          {t('open')}
        </Link>
      }
    >
      <div className="@container grid grid-cols-2 divide-x divide-line-2">
        {basket(pair.base, 0, s.basket.base)}
        {basket(pair.other, 1, s.basket.other, <Pct v={s.medianGapPct} />)}
      </div>
      <div
        role="img"
        aria-label={t('tally', { base, a, e, other, b })}
        className="mx-5 mt-2 mb-1 flex h-2.5 overflow-hidden rounded-full bg-line-2"
      >
        {seg(a, retailerColor(pair.base, 0))}
        {seg(e, 'var(--color-line-3)')}
        {seg(b, retailerColor(pair.other, 1))}
      </div>
      <p className="flex flex-wrap gap-x-4 gap-y-1 px-5 pb-4 text-[13px] text-ink-2">
        <span>{t.rich('cheaperAt', { n: a, shop: base, b: strong })}</span>
        <span>{t.rich('same', { n: e, b: strong })}</span>
        <span>{t.rich('cheaperAt', { n: b, shop: other, b: strong })}</span>
        <span className="ms-auto">{t('scope', { n: s.n, total: data.total })}</span>
      </p>
    </Card>
  );
}

const strong = (c: ReactNode) => <b className="font-semibold text-ink">{c}</b>;

/**
 * The deepest discounts, one card per retailer whose was-prices are verified (/summary measures
 * them or says why not); a retailer whose discounts are not measured gets one chip at the foot.
 */
function TopDiscounts({ rows }: { rows: readonly RetailerSummary[] }) {
  const tt = useTranslations('widgets.top');
  const tk = useTranslations('widgets.kpi');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const many = rows.length > 1;
  const promos = rows.map((r) => ({ r, p: promotions(r.data) }));
  const measured = promos.filter((x) => x.p.measured && x.p.top.length > 0);
  if (measured.length === 0) return null;
  const folds = promos.filter((x) => !x.p.measured);
  return (
    <>
      {measured.map(({ r, p }, i) =>
        p.measured ? (
          <Card
            key={r.retailer}
            id={`w-top${i === 0 ? '' : `-${r.retailer}`}`}
            title={many ? tt('titleAt', { shop: r.name }) : tt('title')}
            flush
            tools={
              <Link href={promotionsHref(locale, {})} className="btn text-sm focus-visible:outline-2">
                {tt('all')}
              </Link>
            }
          >
            <TopDiscountsWidget data={p.top} locale={locale} retailer={r.retailer} />
            {i === measured.length - 1 &&
              folds.map(({ r: f, p: fp }) => (
                <p
                  key={f.retailer}
                  className="mt-2 flex items-center gap-2 border-t border-line-2 px-5 pt-3 pb-1 text-[13px] text-ink-2"
                >
                  <RetailerDot id={f.retailer} index={rows.indexOf(f)} />
                  <span>{f.name}</span>
                  <Tip text={!fp.measured ? <Known t={tr} v={fp.reason} /> : null}>
                    <span className="pill bg-surface-2">{tk('none')}</span>
                  </Tip>
                </p>
              ))}
          </Card>
        ) : null,
      )}
    </>
  );
}
