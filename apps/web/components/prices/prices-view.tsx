'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { GroupBy } from '@/lib/compare';
import { formatCount } from '@/lib/format';
import { formatMoney } from '@/lib/money';
import { ErrorNotice } from '../error-notice';
import { Card, CardGrid } from '../ui/card';
import { CaveatNotes } from '../ui/env-notes';
import { Known } from '../ui/known';
import { PageHeader } from '../ui/page-header';
import { Loading, Skeleton } from '../ui/skeleton';
import { CROSS_COLS, CROSS_ROWS, MIN_PAIRS } from '../widgets/constants';
import { PairKpis, type RetailerSummary } from '../widgets/kpis';
import {
  brandShare,
  categoryNodes,
  cheaperShares,
  compareHref,
  crossCells,
  gapRows,
  ladderRows,
  pct,
} from '../widgets/model';
import { useCompareData, useIndexData, useRetailers } from '../widgets/use-compare';
import { useSummaries } from '../widgets/use-summaries';

const charts = () => import('../widgets/charts');
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
const IndexTrendWidget = dynamic(() => charts().then((m) => m.IndexTrendWidget), {
  ssr: false,
  loading: ChartSkeleton,
});
const TopGapsWidget = dynamic(() => charts().then((m) => m.TopGapsWidget), {
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
const GroupGapWidget = dynamic(() => charts().then((m) => m.GroupGapWidget), {
  ssr: false,
  loading: ChartSkeleton,
});

const TOPS = [5, 10, 20] as const;
type Top = (typeof TOPS)[number];
type Pair = NonNullable<ReturnType<typeof useRetailers>['pair']>;

/**
 * Price analytics: one retailer's full catalogue at a time (distribution, ladder, brand and
 * category positioning), then the pair head to head on the matched products only, with the
 * comparable-pair count beside every head-to-head figure. The retailer, the brand count and the
 * grouping live in the URL.
 */
export function PricesView() {
  const t = useTranslations('prices');
  const tw = useTranslations('widgets');
  const locale = useLocale();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
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
  // Rows are keyed by the retailer the API answered for; the asked-for id is the fallback.
  const row =
    s.rows.find((r) => r.retailer === selected) ?? s.rows[selected ? ids.indexOf(selected) : 0] ?? s.rows[0];
  const topRaw = Number(sp.get('top'));
  const top: Top = (TOPS as readonly number[]).includes(topRaw) ? (topRaw as Top) : 10;
  const groupBy: GroupBy = sp.get('groupBy') === 'category' ? 'category' : 'brand';

  return (
    <div className="space-y-8">
      <PageHeader id="prices-title" title={t('title')} intro={<p>{t('intro')}</p>} />
      {error ? (
        <ErrorNotice error={error} />
      ) : loading || (s.loading && s.rows.length === 0) ? (
        <Loading kind="chart">{t('loading')}</Loading>
      ) : ids.length === 0 || (!row && !s.error) ? (
        <p className="text-sm text-ink-2">{t('noRetailers')}</p>
      ) : (
        <>
          <section aria-labelledby="per-retailer" className="space-y-4">
            <SectionHead id="per-retailer" title={t('perRetailer')} hint={t('perRetailerHint')}>
              {ids.length > 1 && (
                <Segmented
                  label={tw('controls.retailer')}
                  value={selected ?? ''}
                  options={ids.map((id) => ({
                    value: id,
                    label: s.rows.find((r) => r.retailer === id)?.name ?? id,
                  }))}
                  onChange={(v) => set('retailer', v === ids[0] ? null : v)}
                />
              )}
            </SectionHead>
            {s.error && !row && <ErrorNotice error={s.error.error} onRetry={s.error.retry} />}
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
            <HeadToHead
              pair={pair}
              locale={locale}
              groupBy={groupBy}
              onGroupBy={(v) => set('groupBy', v === 'brand' ? null : v)}
              top={top}
            />
          ) : (
            <section aria-labelledby="head-to-head" className="space-y-4">
              <SectionHead id="head-to-head" title={t('headToHead')} hint={t('onePair')} />
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

/** A small group of real buttons, the pressed one filled; the label names the group for readers. */
function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1 rounded-ctl bg-surface-2 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`rounded-[8px] px-3 py-1 text-sm focus-visible:outline-2 ${
            o.value === value ? 'bg-surface font-semibold text-ink shadow-card' : 'text-ink-2 hover:text-ink'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
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
  return (
    <div className="space-y-4">
      <CaveatNotes caveats={row.caveats} />
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
        {d.priceHist && d.priceHist.counts.some((c) => c > 0) && (
          <Card id="p-hist" title={tw('hist.title')} question={tw('hist.question')} span={6}>
            <PriceHistWidget data={d.priceHist} {...p} />
          </Card>
        )}
        {d.ladder && ladderRows(d.ladder).length > 0 && (
          <Card id="p-ladder" title={tw('ladder.title')} question={tw('ladder.question')} span={6}>
            <LadderWidget data={d.ladder} {...p} />
          </Card>
        )}
        {d.brandPrice && d.brandPrice.length > 0 && (
          <Card
            id="p-brands"
            title={tw('brands.title')}
            question={tw('brands.question', { n: Math.min(top, d.brandPrice.length) })}
            span={12}
            tools={
              <Segmented
                label={tw('controls.topLabel')}
                value={top}
                options={topOptions.filter((o) => o.value <= Math.max(5, d.brandPrice!.length))}
                onChange={onTop}
              />
            }
          >
            <BrandPriceWidget data={d.brandPrice} top={top} {...p} />
          </Card>
        )}
        {d.categoryMix && categoryNodes(d.categoryMix).length > 0 && (
          <Card id="p-mix" title={tw('mix.title')} question={tw('mix.question')} span={6}>
            <CategoryMixWidget data={d.categoryMix} {...p} />
          </Card>
        )}
        {d.brandPrice && d.priced && brandShare(d.brandPrice, d.priced).length > 0 && (
          <Card id="p-share" title={tw('share.title')} question={tw('share.question')} span={6}>
            <BrandShareWidget data={d.brandPrice} priced={d.priced} {...p} />
          </Card>
        )}
        {d.ratingPrice && d.ratingPrice.points.length > 0 && (
          <Card id="p-rating" title={tw('rating.title')} question={tw('rating.question')} span={12}>
            <RatingPriceWidget data={d.ratingPrice} {...p} />
            <p className="mt-1 text-xs text-ink-2">
              {tw('rating.note', {
                rated: pct(d.ratingPrice.ratedPct, locale),
                n: formatCount(d.ratingPrice.n, locale),
                k: d.ratingPrice.points.length,
              })}
            </p>
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

/** The pair on the matched set only; every card's question carries the pair count. */
function HeadToHead({
  pair,
  locale,
  groupBy,
  onGroupBy,
  top,
}: {
  pair: Pair;
  locale: string;
  groupBy: GroupBy;
  onGroupBy: (v: GroupBy) => void;
  top: Top;
}) {
  const t = useTranslations('prices');
  const tw = useTranslations('widgets');
  const tc = useTranslations('card');
  const tr = useTranslations('reasons');
  const cmp = useCompareData(pair, null, 500);
  const truncated = cmp.kind === 'ready' && cmp.data.truncated;
  const grouped = useCompareData(pair, groupBy);
  const otherGrouped = useCompareData(truncated ? pair : null, groupBy === 'brand' ? 'category' : 'brand');
  const idx = useIndexData(pair);
  const names = { base: pair.name(pair.base), other: pair.name(pair.other) };
  const href = compareHref(locale, pair);
  const head = (
    <SectionHead id="head-to-head" title={t('headToHead')} hint={t('headToHeadHint', names)}>
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
          {t('noPairs')} {cmp.env.reason && <Known t={tr} v={cmp.env.reason} />}
        </p>
      </section>
    );
  const data = cmp.data;
  const n = data.summary?.n ?? 0;
  const on = (q: string) => tw('onPairs', { n, desc: q });
  const gaps = gapRows(data.rows, top);
  const cross = truncated
    ? null
    : crossCells(data.rows, { min: MIN_PAIRS, maxRows: CROSS_ROWS, maxCols: CROSS_COLS });
  const currency = data.summary?.basket.base.currency ?? gaps[0]?.basePrice?.currency ?? '';
  const by = (g: GroupBy) => tw(g === 'brand' ? 'cheaperShare.byBrand' : 'cheaperShare.byCategory');
  const groupOptions = (['brand', 'category'] as const).map((g) => ({ value: g, label: by(g) }));
  const shareCard = (state: typeof grouped, g: GroupBy, span: 6 | 12) => (
    <Card
      id={`p-share-${g}`}
      title={tw('cheaperShare.title', { by: by(g) })}
      question={on(tw('cheaperShare.question', { by: by(g) }))}
      span={span}
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
          groupBy={g}
        />
      ) : state.kind === 'ready' ? (
        <p className="text-sm text-ink-2">{thinText(tw, state.data.groups)}</p>
      ) : null}
    </Card>
  );
  return (
    <section aria-labelledby="head-to-head" className="space-y-4">
      {head}
      <p className="text-sm">{t('pairsNote', { n, ...names })}</p>
      <PairKpis data={data} pair={pair} locale={locale} href={href} />
      <CardGrid>
        {cross && cross.cells.length > 0 && (
          <Card id="p-cross" title={tw('cross.title')} question={on(tw('cross.question'))} span={12}>
            <CrossHeatmapWidget data={data.rows} currency={currency} locale={locale} pair={pair} />
          </Card>
        )}
        {truncated && (
          <>
            <p className="col-span-12 text-sm text-ink-2">{tw('cross.truncated')}</p>
            {shareCard(grouped, groupBy, 6)}
            {shareCard(otherGrouped, groupBy === 'brand' ? 'category' : 'brand', 6)}
          </>
        )}
        <Card
          id="p-group-gap"
          title={groupBy === 'brand' ? tw('groupGap.title') : tw('groupGap.titleCategory')}
          question={on(tw('groupGap.question', { by: by(groupBy), other: names.other }))}
          span={12}
          state={grouped.kind === 'loading' ? 'loading' : grouped.kind === 'error' ? 'error' : 'ready'}
          skeleton="chart"
          reason={
            grouped.kind === 'error' ? (
              <ErrorNotice error={grouped.error} onRetry={grouped.retry} />
            ) : undefined
          }
          tools={
            <Segmented
              label={tw('controls.groupBy')}
              value={groupBy}
              options={groupOptions}
              onChange={onGroupBy}
            />
          }
        >
          {grouped.kind === 'ready' && grouped.data.groups.some((g) => g.summary) ? (
            <GroupGapWidget
              data={grouped.data.groups}
              currency={currency}
              locale={locale}
              pair={pair}
              groupBy={groupBy}
            />
          ) : grouped.kind === 'ready' ? (
            <p className="text-sm text-ink-2">{thinText(tw, grouped.data.groups)}</p>
          ) : null}
        </Card>
        {gaps.length > 0 && (
          <Card id="p-gaps" title={tw('gaps.title')} question={on(tw('gaps.question'))} span={8}>
            <TopGapsWidget data={data.rows} currency={currency} locale={locale} pair={pair} top={top} />
          </Card>
        )}
        <Card
          id="p-index"
          title={tw('index.title')}
          question={on(tw('index.question', names))}
          span={gaps.length > 0 ? 4 : 12}
          state={idx.kind === 'loading' ? 'loading' : 'ready'}
          skeleton="chart"
        >
          {idx.kind === 'ready' ? (
            <IndexTrendWidget data={idx.data} currency={currency} locale={locale} pair={pair} />
          ) : idx.kind === 'error' ? (
            <ErrorNotice error={idx.error} onRetry={idx.retry} />
          ) : (
            <p className="text-sm text-ink-2">{tw('index.noHistory')}</p>
          )}
        </Card>
      </CardGrid>
    </section>
  );
}

/** Every group too thin to count, by name, with the API's reason implied: too few pairs. */
function thinText(
  tw: ReturnType<typeof useTranslations>,
  groups: readonly { key: string; summary: unknown }[],
) {
  const thin = groups.filter((g) => !g.summary);
  return tw('cheaper.thin', { n: thin.length, list: thin.map((g) => g.key).join(', ') });
}
