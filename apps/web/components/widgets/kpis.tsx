'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Summary } from '@/lib/api/summary';
import { num } from '@/lib/api/summary';
import type { Schemas } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import { formatMoney } from '@/lib/money';
import type { CaveatView } from '@/lib/api/types';
import { exploreHref, freshness, hasParents, importedOn, pct, promotions, promotionsHref } from './model';

/** One retailer's /summary, fetched with an explicit `?retailer=`, and the caveats scoped to it. */
export interface RetailerSummary {
  retailer: string;
  name: string;
  data: Summary;
  caveats: readonly CaveatView[];
}

/**
 * The headline numbers, one row per retailer inside each tile so the catalogues read side by side:
 * products, brands, categories, median price, the promotion share where it is measured, and
 * freshness. Each tile opens the list it counts. An imported retailer's count and date say so; a
 * null count is withheld by /summary, never zero.
 */
export function KpiWidget({ rows, locale }: { rows: readonly RetailerSummary[]; locale: string }) {
  const t = useTranslations('widgets.kpi');
  const lc = locale === 'ar' ? 'ar' : 'en';
  const all = exploreHref(locale, {});
  const many = rows.length > 1;
  const promoRows = rows.filter((r) => promotions(r.data).measured);
  const count = (v: number | null) => (v === null ? <None>{t('none')}</None> : formatCount(v, locale));
  const per = (f: (r: RetailerSummary) => ReactNode, sub?: (r: RetailerSummary) => ReactNode) =>
    rows.map((r) => (
      <Row key={r.retailer} name={many ? r.name : undefined} sub={sub?.(r)}>
        {f(r)}
      </Row>
    ));
  return (
    <dl
      className={`grid grid-cols-2 gap-4 sm:grid-cols-3 ${promoRows.length ? 'xl:grid-cols-6' : 'xl:grid-cols-5'}`}
    >
      <Tile k={t('products')} href={all} tone="bg-lav">
        {per(
          (r) => count(r.data.products),
          (r) => (hasParents(r.caveats, r.retailer) ? t('productsParents') : undefined),
        )}
      </Tile>
      <Tile k={t('brands')} href={all} tone="bg-sky">
        {per((r) => count(r.data.brands))}
      </Tile>
      <Tile k={t('categories')} href={all} tone="bg-mint">
        {per((r) => count(r.data.categories))}
      </Tile>
      <Tile k={t('median')} href={exploreHref(locale, { sort: 'price_asc' })} tone="bg-butter">
        {per((r) => (r.data.medianPrice ? formatMoney(r.data.medianPrice, lc) : <None>{t('none')}</None>))}
      </Tile>
      {promoRows.length > 0 && (
        <Tile
          k={t('promo')}
          href={promotionsHref(locale, {})}
          tone="bg-blush"
          sub={
            many && promoRows.length === 1 ? t('promoOnly', { retailer: promoRows[0]!.name }) : t('promoOf')
          }
        >
          {per((r) => {
            const p = promotions(r.data);
            // Withheld promotions show as not measured, never as 0%.
            return p.measured ? pct(p.share, locale) : <None>{t('withheld')}</None>;
          })}
        </Tile>
      )}
      <Tile k={t('freshness')} href="#dataset" tone="bg-surface-2">
        {per(
          (r) => (
            <FreshPill data={r.data} caveats={r.caveats} />
          ),
          (r) => (
            <FreshNote data={r.data} caveats={r.caveats} locale={locale} />
          ),
        )}
      </Tile>
    </dl>
  );
}

function FreshPill({ data, caveats }: { data: Summary; caveats: readonly CaveatView[] }) {
  const t = useTranslations('widgets.kpi');
  const f = freshness(data.freshness);
  // An imported snapshot reads as a snapshot even when the API's status is a collected one.
  const k =
    f === 'fresh' || f === 'aging' || f === 'stale'
      ? importedOn(caveats, data.retailer)
        ? 'snapshot'
        : f
      : f;
  const tone =
    k === 'fresh'
      ? 'bg-mint text-mint-ink'
      : k === 'aging'
        ? 'bg-butter text-butter-ink'
        : k === 'stale'
          ? 'bg-rose text-rose-ink'
          : 'bg-surface-2 text-ink';
  return <span className={`pill text-sm ${tone}`}>{t(k)}</span>;
}

/** An import date, never a capture date: no 'as of' and no age (owner rule, API 1.5.0). */
function FreshNote({
  data,
  caveats,
  locale,
}: {
  data: Summary;
  caveats: readonly CaveatView[];
  locale: string;
}) {
  const t = useTranslations('widgets.kpi');
  const f = freshness(data.freshness);
  const imported =
    f === 'snapshot'
      ? (importedOn(caveats, data.retailer) ?? data.freshness.cutoff)
      : importedOn(caveats, data.retailer);
  if (imported) return <>{t('imported', { date: formatDate(imported, locale) })}</>;
  return (
    <>
      {t('asOf', { date: formatDate(data.freshness.cutoff, locale) })}
      {' · '}
      {t('age', { days: data.freshness.ageDays })}
    </>
  );
}

/**
 * The head-to-head numbers for one pair, on the matched set only: how many comparable pairs, the
 * median gap on them, and who is cheaper how often. Every tile names the pair count, so none reads
 * as a full-catalogue comparison. A null summary is too few pairs, never zero.
 */
export function PairKpis({
  data,
  pair,
  locale,
  href,
}: {
  data: Schemas['Comparison'];
  pair: { base: string; other: string; name: (id: string) => string };
  locale: string;
  href: string;
}) {
  const t = useTranslations('widgets.kpi');
  const tr = useTranslations('reasons');
  const s = data.summary;
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const reason = data.sides.base.reason ?? data.sides.other.reason;
  const none = <None>{reason && tr.has(reason) ? tr(reason) : t('none')}</None>;
  const gap = s ? num(s.medianGapPct) : NaN;
  return (
    <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
      <Tile k={t('pairs')} href={href} tone="bg-lav" sub={t('pairsOf', { base, other })}>
        <Row>{s ? formatCount(s.n, locale) : none}</Row>
      </Tile>
      <Tile
        k={t('index')}
        href={href}
        tone="bg-sky"
        sub={s ? t('indexOf', { other, base, n: formatCount(s.n, locale) }) : undefined}
      >
        <Row>
          {s && Number.isFinite(gap) ? (
            <span className={gap > 0 ? 'text-series-a' : gap < 0 ? 'text-series-b' : undefined}>
              {gap > 0 ? '+' : ''}
              {pct(s.medianGapPct, locale)}
            </span>
          ) : (
            none
          )}
        </Row>
      </Tile>
      <Tile
        k={t('cheaper')}
        href={href}
        tone="bg-mint"
        sub={s ? t('same', { n: formatCount(s.equalCount, locale) }) : undefined}
      >
        {s ? (
          <>
            <Row name={base}>{formatCount(s.cheaperCounts[pair.base] ?? 0, locale)}</Row>
            <Row name={other}>{formatCount(s.cheaperCounts[pair.other] ?? 0, locale)}</Row>
          </>
        ) : (
          <Row>{none}</Row>
        )}
      </Tile>
    </dl>
  );
}

function Tile({
  k,
  href,
  tone,
  sub,
  children,
}: {
  k: string;
  href: string;
  tone: string;
  sub?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="panel relative min-w-0 overflow-hidden px-4 pt-4 pb-3.5">
      <span aria-hidden className={`absolute inset-x-0 top-0 h-1 ${tone}`} />
      <dt className="text-[13px] font-semibold text-ink-2">
        <Link href={href} className="after:absolute after:inset-0 hover:underline focus-visible:outline-2">
          {k}
        </Link>
      </dt>
      <div className="mt-1.5 space-y-1.5">{children}</div>
      {sub && <dd className="mt-1 text-xs text-ink-2">{sub}</dd>}
    </div>
  );
}

/** One retailer's value in a tile; the name only when the tile holds more than one. */
function Row({ name, sub, children }: { name?: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <dd className="min-w-0">
      {name && <span className="block truncate text-xs font-medium text-ink-2">{name}</span>}
      <span className="block text-2xl leading-tight font-bold tracking-tight tabular-nums">{children}</span>
      {sub && <span className="mt-0.5 block text-xs text-ink-2">{sub}</span>}
    </dd>
  );
}

const None = ({ children }: { children: ReactNode }) => (
  <span className="text-base font-medium text-ink-2">{children}</span>
);
