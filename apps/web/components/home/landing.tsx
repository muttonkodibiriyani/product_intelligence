'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { CategoryCompare } from '@/lib/api/category-compare';
import { formatCount, formatDate, loc } from '@/lib/format';
import { navHref } from '@/lib/nav';
import type { Money as MoneyValue, Schemas } from '@/lib/api/types';
import { DatasetStatus } from '../dataset-status';
import { ErrorNotice } from '../error-notice';
import { Card } from '../ui/card';
import { Known } from '../ui/known';
import { Money, Pct } from '../ui/money';
import { PageHeader } from '../ui/page-header';
import { RetailerDot } from '../ui/retailer-dot';
import { Loading, Skeleton } from '../ui/skeleton';
import { KpiBand, type RetailerSummary } from '../widgets/kpis';
import { TopDiscountsWidget } from '../widgets/top-discounts';
import { useCategoryCompare } from '../widgets/use-category';
import { useCompareData, useRetailers, type PairState } from '../widgets/use-compare';
import { useSummaries } from '../widgets/use-summaries';
import {
  compareHref,
  exploreHref,
  freshness,
  importedOn,
  promotions,
  promotionsHref,
} from '../widgets/model';
import { CategoryHeadToHead } from './category-head-to-head';
import { categoryRead, earlyExcluded, retailerTone, verdict, type CategoryRead } from './model';

type Pair = NonNullable<ReturnType<typeof useRetailers>['pair']>;
type Comparison = Schemas['Comparison'];

/**
 * The Overview: one sentence on who is cheaper, the band of four numbers, where each shop is
 * cheaper by category, the matched basket head to head, and the deepest discounts. Every number
 * comes from the API with the list it was counted from one click away.
 */
export function Landing() {
  const t = useTranslations('home.landing');
  const { ids, pair, loading, error } = useRetailers();
  const s = useSummaries(ids);
  return (
    <div className="space-y-6">
      <PageHeader title={t('overview')} intro={<Subtitle rows={s.rows} />} />
      {error ? (
        <ErrorNotice error={error} />
      ) : loading ? (
        <Loading kind="chart">{t('loading')}</Loading>
      ) : (
        <Overview s={s} pair={pair} />
      )}
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

function Overview({ s, pair }: { s: ReturnType<typeof useSummaries>; pair: Pair | null }) {
  const t = useTranslations('home.landing');
  const tc = useTranslations('card');
  const locale = useLocale();
  // The pair's matched set and category medians; neither is asked for without a second retailer.
  const cmp = useCompareData(pair);
  const cat = useCategoryCompare(pair);

  if (s.error && s.rows.length === 0) return <ErrorNotice error={s.error.error} onRetry={s.error.retry} />;
  if (s.loading && s.rows.length === 0) return <Loading kind="chart">{tc('loading')}</Loading>;
  // Nothing to report on (every retailer withheld or thin): the dataset below says why.
  if (s.rows.length === 0)
    return (
      <div className="space-y-6">
        <p className="text-sm text-ink-2">{t('noRetailers')}</p>
        <Dataset />
      </div>
    );

  const read = pair && cat.kind === 'ready' ? categoryRead(cat.data.buckets, pair.base, pair.other) : null;
  const matched = cmp.kind === 'ready' && cmp.data.summary !== null && cmp.data.summary.n > 0;
  return (
    <div className="space-y-6">
      {pair && <Headline pair={pair} cmp={cmp} read={read} cat={cat} />}
      <section id="kpi-band" aria-labelledby="kpi-band-title">
        <h2 id="kpi-band-title" className="sr-only">
          {t('numbers')}
        </h2>
        <KpiBand rows={s.rows} locale={locale} pair={pair} categories={read} />
      </section>
      {pair && (
        <div className="grid grid-cols-12 items-start gap-5">
          <CategoryHeadToHead state={cat} pair={pair} span={matched ? 8 : 12} />
          {matched && <MatchedBasket pair={pair} data={cmp.data} />}
        </div>
      )}
      <TopDiscounts rows={s.rows} />
      <Dataset />
    </div>
  );
}

/**
 * The one-line answer, from /compare's own counts: who is cheaper on how many of the matched
 * products, what the same basket costs at each shop, and how many of the products either shop
 * sells that is (`total` counts every product offered at either shop, matched or not). It is an
 * "early read" only when the API's own early_excluded caveat says items were left out, never by
 * default. Without a matched product yet it says so, with what is ready and the category read.
 */
export function Headline({
  pair,
  cmp,
  read,
  cat,
}: {
  pair: Pair;
  cmp: PairState<Comparison>;
  read: CategoryRead | null;
  cat: PairState<CategoryCompare>;
}) {
  const t = useTranslations('home.landing.headline');
  const tc = useTranslations('card');
  const locale = useLocale();
  if (cmp.kind === 'loading')
    return (
      <div className="panel px-5 py-4" aria-busy>
        <Skeleton kind="lines" rows={2} />
        <p role="status" className="mt-2 text-sm text-ink-2">
          {tc('loading')}
        </p>
      </div>
    );
  if (cmp.kind === 'error') return <ErrorNotice error={cmp.error} onRetry={cmp.retry} />;
  const data = cmp.kind === 'ready' ? cmp.data : null;
  const s = data?.summary ?? null;
  if (!data || !s || s.n === 0)
    return (
      <EmptyHeadline
        pair={pair}
        data={data}
        reason={cmp.kind === 'empty' ? cmp.env?.reason : null}
        read={read}
        cat={cat}
      />
    );

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
    <section className="panel px-5 py-4" aria-labelledby="headline-title">
      <h2 id="headline-title" className="text-lg leading-snug font-semibold tracking-tight">
        {early && <span className="text-ink-2">{t('early')} </span>}
        {v.kind === 'allSame'
          ? t('allSame', { n: v.n, base, other })
          : v.kind === 'tie'
            ? t('tie', { k: v.k, n: v.n, base, other })
            : t.rich('lead', {
                shop: leader,
                k: v.k,
                n: v.n,
                b: (c) => <b style={{ color: retailerTone(leaderId!, v.leader === 'base' ? 0 : 1) }}>{c}</b>,
              })}
        {tail && ` ${tail}`}
      </h2>
      <p className="mt-1.5 text-sm text-ink-2">
        {t.rich('basket', {
          n: s.n,
          base,
          other,
          baseAmount: () => <Money m={s.basket.base} locale={locale} />,
          otherAmount: () => <Money m={s.basket.other} locale={locale} />,
          pct: () => <Pct v={s.medianGapPct} />,
          b: strong,
        })}
        {` ${t('scope', { n: s.n, total: data.total })}`}
        {early && ` ${loc(early.caveat, locale)}`}{' '}
        <Link
          href={compareHref(locale, pair)}
          className="font-medium text-ink underline underline-offset-2 focus-visible:outline-2"
        >
          {t('see', { n: s.n })}
        </Link>
      </p>
    </section>
  );
}

/**
 * No matched product yet: one sentence, what each side has ready (the API's own observed counts
 * and how many products either shop sells), the category read when the medians are served, and
 * the two places to go. A count the API did not send (no summary) is left out, never shown as 0.
 */
export function EmptyHeadline({
  pair,
  data,
  reason,
  read,
  cat,
}: {
  pair: Pair;
  data: Comparison | null;
  reason?: string | null;
  read: CategoryRead | null;
  cat: PairState<CategoryCompare>;
}) {
  const t = useTranslations('home.landing.empty');
  const th = useTranslations('home.landing');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const sides = data ? [data.sides.base, data.sides.other] : null;
  const category =
    read && read.compared > 0
      ? read.base === read.other
        ? read.base > 0
          ? t('categoryTie', { k: read.base, n: read.compared, base, other })
          : t('categorySame', { n: read.compared, base, other })
        : t('categoryRead', {
            shop: read.base > read.other ? base : other,
            k: Math.max(read.base, read.other),
            n: read.compared,
          })
      : cat.kind === 'loading'
        ? null
        : t('categoryNone');
  return (
    <section className="panel px-5 py-4" aria-labelledby="headline-title">
      <h2 id="headline-title" className="text-lg leading-snug font-semibold tracking-tight">
        {t('title', { base, other })}
      </h2>
      <p className="mt-1.5 text-sm text-ink-2">
        {t('why')} {reason && <Known t={tr} v={reason} />} {category}
      </p>
      {sides && (
        <ul className="mt-4 grid gap-3 sm:grid-cols-3">
          {[pair.base, pair.other].map((id, i) => (
            <li key={id} className="rounded-ctl bg-surface-2 px-4 py-3">
              <p className="flex items-center gap-1.5 text-xs font-medium text-ink-2">
                <RetailerDot id={id} side={i === 0 ? 0 : 1} />
                {pair.name(id)}
              </p>
              <p className="mt-1 text-xl font-semibold tabular-nums">
                {formatCount(sides[i]!.observed, locale)}
              </p>
              <p className="text-xs text-ink-2">
                {t('observed', { n: sides[i]!.observed })}
                {sides[i]!.reason && (
                  <>
                    {' · '}
                    <Known t={tr} v={sides[i]!.reason!} />
                  </>
                )}
              </p>
            </li>
          ))}
          <li className="rounded-ctl bg-surface-2 px-4 py-3">
            <p className="text-xs font-medium text-ink-2">{t('eitherShop')}</p>
            <p className="mt-1 text-xl font-semibold tabular-nums">{formatCount(data!.total, locale)}</p>
            {data!.summary && <p className="text-xs text-ink-2">{t('confirmed', { n: data!.summary.n })}</p>}
          </li>
        </ul>
      )}
      <p className="mt-4 flex flex-wrap gap-2">
        <Link href={navHref('prices', locale)} className="btn btn-primary text-sm focus-visible:outline-2">
          {th('openPrices')}
        </Link>
        <Link href={exploreHref(locale, {})} className="btn text-sm focus-visible:outline-2">
          {t('browse')}
        </Link>
      </p>
    </section>
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
  const basket = (id: string, side: 0 | 1, m: MoneyValue, gap?: ReactNode) => (
    <div className="min-w-0 px-5 py-3.5">
      <p className="flex items-center gap-1.5 text-xs text-ink-2">
        <RetailerDot id={id} side={side} />
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
        {seg(a, retailerTone(pair.base, 0))}
        {seg(e, 'var(--color-line-3)')}
        {seg(b, retailerTone(pair.other, 1))}
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
 * them or says why not); a retailer whose discounts are not available yet gets one line at the foot.
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
            question={tt('question')}
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
                  <RetailerDot id={f.retailer} side={rows.indexOf(f) === 0 ? 0 : 1} />
                  <span>
                    {tk('notAvailable', { shop: f.name })} {!fp.measured && <Known t={tr} v={fp.reason} />}
                  </span>
                </p>
              ))}
          </Card>
        ) : null,
      )}
    </>
  );
}

function Dataset() {
  return (
    <section id="dataset" className="panel scroll-mt-6 px-5 py-4">
      <DatasetStatus nested />
    </section>
  );
}
