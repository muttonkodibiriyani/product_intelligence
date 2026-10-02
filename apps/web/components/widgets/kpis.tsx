'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Summary } from '@/lib/api/summary';
import { num } from '@/lib/api/summary';
import type { Schemas } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import { formatMoney, isValidPrice } from '@/lib/money';
import { navHref } from '@/lib/nav';
import type { CaveatView, Money as MoneyValue } from '@/lib/api/types';
import { abs, deepestCut, minus, retailerTone, share, type CategoryRead } from '../home/model';
import { Known } from '../ui/known';
import { Money } from '../ui/money';
import { RetailerDot } from '../ui/retailer-dot';
import { exploreHref, freshness, hasParents, importedOn, pct, promotions, promotionsHref } from './model';

/** One retailer's /summary, fetched with an explicit `?retailer=`, and the caveats scoped to it. */
export interface RetailerSummary {
  retailer: string;
  name: string;
  data: Summary;
  caveats: readonly CaveatView[];
}

type Pair = { base: string; other: string; name: (id: string) => string };

/**
 * The band of four: products tracked, the category read (or the median price until the category
 * comparison is served), the promotion share, and freshness. One hero number per card, both
 * shops' values under it with count bars, and a "who leads" line worked out from the two values
 * shown; a value the API withheld reads as its state string, never as 0. Each card opens the
 * list it counts.
 */
export function KpiBand({
  rows,
  locale,
  pair = null,
  categories = null,
}: {
  rows: readonly RetailerSummary[];
  locale: string;
  pair?: Pair | null;
  /** The category read, once /category-compare is served; the card falls back to medians. */
  categories?: CategoryRead | null;
}) {
  const t = useTranslations('widgets.kpi');
  const tr = useTranslations('reasons');
  const many = rows.length > 1;
  const none = <None>{t('none')}</None>;
  const side = (i: number): 0 | 1 => (i === 0 ? 0 : 1);

  // Products: the two counts, their sum, and who lists more.
  const products = rows.map((r) => r.data.products);
  const known = products.filter((v): v is number => v !== null);
  const maxProducts = Math.max(0, ...known);
  const productsLead =
    rows.length === 2 && products[0] !== null && products[1] !== null
      ? products[0] === products[1]
        ? t('sameProducts')
        : t('moreProducts', {
            shop: rows[products[0]! > products[1]! ? 0 : 1]!.name,
            n: formatCount(Math.abs(products[0]! - products[1]!), locale),
          })
      : null;

  // Promotions: the measured shares, and the deepest cut among their top discounts.
  const promos = rows.map((r) => ({ r, p: promotions(r.data) }));
  const measured = promos.filter((x) => x.p.measured);
  const maxShare = Math.max(0, ...measured.map((x) => (x.p.measured ? Number(x.p.share) : 0)));
  const deepest = measured
    .map((x) => ({ r: x.r, cut: x.p.measured ? deepestCut(x.p.top) : null }))
    .filter((x): x is { r: RetailerSummary; cut: string } => x.cut !== null)
    .sort((a, b) => Number(b.cut) - Number(a.cut))[0];
  const first = measured[0];

  return (
    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tile
        k={t('products')}
        href={exploreHref(locale, {})}
        src={many && known.length === rows.length ? t('bothShops') : undefined}
        hero={
          known.length
            ? formatCount(
                known.reduce((a, b) => a + b, 0),
                locale,
              )
            : none
        }
        lead={productsLead}
      >
        {rows.map((r, i) => (
          <ShopRow
            key={r.retailer}
            id={r.retailer}
            side={side(i)}
            name={many ? r.name : undefined}
            bar={r.data.products === null ? null : share(r.data.products, maxProducts)}
            sub={hasParents(r.caveats, r.retailer) ? t('productsParents') : undefined}
          >
            {r.data.products === null ? none : formatCount(r.data.products, locale)}
          </ShopRow>
        ))}
      </Tile>
      {pair && categories && categories.compared > 0 ? (
        <CategoryTile pair={pair} read={categories} locale={locale} />
      ) : (
        <MedianTile rows={rows} locale={locale} />
      )}
      <Tile
        k={t('promo')}
        href={promotionsHref(locale, {})}
        hero={first?.p.measured ? pct(first.p.share, locale) : none}
        small={first ? (many ? t('promoOfShop', { shop: first.r.name }) : t('promoOf')) : undefined}
        lead={deepest ? t('deepestCut', { shop: deepest.r.name, pct: pct(deepest.cut, locale) }) : null}
      >
        {promos.map(({ r, p }, i) =>
          p.measured ? (
            <ShopRow
              key={r.retailer}
              id={r.retailer}
              side={side(i)}
              name={many ? r.name : undefined}
              bar={share(Number(p.share), maxShare)}
            >
              {pct(p.share, locale)}
            </ShopRow>
          ) : (
            <State key={r.retailer} id={r.retailer} side={side(i)}>
              {t('notAvailable', { shop: r.name })} <Known t={tr} v={p.reason} />
            </State>
          ),
        )}
      </Tile>
      <FreshnessTile rows={rows} locale={locale} />
    </dl>
  );
}

/** In how many of the compared categories each shop's median is the lower; ties and all-same say so. */
function CategoryTile({ pair, read, locale }: { pair: Pair; read: CategoryRead; locale: string }) {
  const t = useTranslations('widgets.kpi');
  const n = formatCount(read.compared, locale);
  const lead = read.base === read.other ? null : read.base > read.other ? pair.base : pair.other;
  const hero = formatCount(lead ? Math.max(read.base, read.other) : read.base || read.same, locale);
  const small =
    lead !== null
      ? t('catCheaperAt', { n, shop: pair.name(lead) })
      : read.base > 0
        ? t('catEach', { n })
        : t('catSame', { n });
  const max = Math.max(read.base, read.other, read.same);
  const row = (id: string, side: 0 | 1, v: number) => (
    <ShopRow key={id} id={id} side={side} name={pair.name(id)} bar={share(v, max)}>
      {formatCount(v, locale)}
    </ShopRow>
  );
  return (
    <Tile
      k={t('byCategory')}
      href={navHref('prices', locale)}
      src={t('nCategories', { n: read.compared })}
      hero={hero}
      small={small}
    >
      {lead === pair.other ? row(pair.other, 1, read.other) : row(pair.base, 0, read.base)}
      <ShopRow name={t('catSameRow')} bar={share(read.same, max)}>
        {formatCount(read.same, locale)}
      </ShopRow>
      {lead === pair.other ? row(pair.base, 0, read.base) : row(pair.other, 1, read.other)}
    </Tile>
  );
}

/** The median price of each catalogue: the lower one as the hero, the difference as the lead. */
function MedianTile({ rows, locale }: { rows: readonly RetailerSummary[]; locale: string }) {
  const t = useTranslations('widgets.kpi');
  const many = rows.length > 1;
  const none = <None>{t('none')}</None>;
  const medians = rows.map((r) =>
    r.data.medianPrice && isValidPrice(r.data.medianPrice) ? r.data.medianPrice : null,
  );
  const valid = rows
    .map((r, i) => ({ r, m: medians[i]! }))
    .filter((x): x is { r: RetailerSummary; m: MoneyValue } => !!x.m);
  const lowest = valid.length ? valid.reduce((a, b) => (b.m.minor < a.m.minor ? b : a)) : null;
  const maxMinor = Math.max(0, ...valid.map((x) => x.m.minor));
  const diff = valid.length === 2 ? minus(valid[1]!.m, valid[0]!.m) : null;
  const lead = diff
    ? diff.minor === 0
      ? t('sameMedian')
      : t('lowerMedian', {
          shop: lowest!.r.name,
          amount: formatMoney(abs(diff), locale === 'ar' ? 'ar' : 'en'),
        })
    : null;
  return (
    <Tile
      k={t('median')}
      href={exploreHref(locale, { sort: 'price_asc' })}
      hero={lowest ? <Money m={lowest.m} locale={locale} /> : none}
      small={lowest && many ? t('lowestAt', { shop: lowest.r.name }) : undefined}
      lead={lead}
    >
      {rows.map((r, i) => (
        <ShopRow
          key={r.retailer}
          id={r.retailer}
          side={i === 0 ? 0 : 1}
          name={many ? r.name : undefined}
          bar={medians[i] ? share(medians[i]!.minor, maxMinor) : null}
        >
          {medians[i] ? <Money m={medians[i]!} locale={locale} /> : none}
        </ShopRow>
      ))}
    </Tile>
  );
}

/** How old each shop's data is: the oldest as the hero, each shop's pill and date under it. */
function FreshnessTile({ rows, locale }: { rows: readonly RetailerSummary[]; locale: string }) {
  const t = useTranslations('widgets.kpi');
  const many = rows.length > 1;
  // An imported retailer's date is an import date, never a capture date (owner rule, API 1.5.0).
  const imported = (r: RetailerSummary) =>
    freshness(r.data.freshness) === 'snapshot'
      ? (importedOn(r.caveats, r.retailer) ?? r.data.freshness.cutoff)
      : importedOn(r.caveats, r.retailer);
  const collected = rows.filter((r) => !imported(r) && freshness(r.data.freshness) !== 'unknown');
  const oldest = collected.length ? Math.max(...collected.map((r) => r.data.freshness.ageDays)) : null;
  const first = collected[0];
  return (
    <Tile
      k={t('freshness')}
      href="#dataset"
      hero={oldest !== null ? t('age', { days: oldest }) : rows.some(imported) ? t('snapshot') : t('unknown')}
      lead={
        first
          ? t('collected', { shop: first.name, date: formatDate(first.data.freshness.cutoff, locale) })
          : null
      }
    >
      {rows.map((r, i) => (
        <ShopRow
          key={r.retailer}
          id={r.retailer}
          side={i === 0 ? 0 : 1}
          name={many ? r.name : undefined}
          mid={<FreshPill data={r.data} caveats={r.caveats} />}
        >
          <FreshNote data={r.data} caveats={r.caveats} locale={locale} />
        </ShopRow>
      ))}
    </Tile>
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
  return <span className={`pill text-xs ${tone}`}>{t(k)}</span>;
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
  return <>{t('asOf', { date: formatDate(data.freshness.cutoff, locale) })}</>;
}

/** One band card: the label (a link to the list it counts), the hero, the lead line, the shop rows. */
function Tile({
  k,
  href,
  src,
  hero,
  small,
  lead,
  children,
}: {
  k: string;
  href: string;
  /** What the hero is over, at the end of the label line ("both catalogues", "9 categories"). */
  src?: string;
  hero: ReactNode;
  /** What the hero counts, after it in small type. */
  small?: string;
  /** The "who leads" line, from the two values shown. */
  lead?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="panel relative flex min-w-0 flex-col gap-2 px-4 pt-4 pb-3.5">
      <dt className="flex items-baseline gap-2 text-[13px] font-semibold text-ink-2">
        <Link href={href} className="after:absolute after:inset-0 hover:underline focus-visible:outline-2">
          {k}
        </Link>
        {src && <span className="ms-auto text-[11px] font-normal text-ink-3">{src}</span>}
      </dt>
      <dd className="text-[28px] leading-none font-semibold tracking-tight tabular-nums">
        {hero}
        {small && <small className="ms-1.5 text-sm font-medium tracking-normal text-ink-2">{small}</small>}
      </dd>
      {lead && <dd className="text-[13px]">{lead}</dd>}
      <dd className="mt-auto grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-1.5 text-xs">
        {children}
      </dd>
    </div>
  );
}

/** One shop's row in a card: dot and name, a count bar (or `mid`), and the value at the end. */
function ShopRow({
  id,
  side = 0,
  name,
  bar,
  mid,
  sub,
  children,
}: {
  id?: string;
  side?: 0 | 1;
  name?: string;
  /** 0…100, the value against the largest on the card; null draws no bar (nothing to size). */
  bar?: number | null;
  mid?: ReactNode;
  sub?: ReactNode;
  children: ReactNode;
}) {
  const fill = id ? retailerTone(id, side) : 'var(--color-ink-3)';
  return (
    <>
      <span className="flex min-w-0 items-center gap-1.5 font-medium text-ink-2">
        {id && <RetailerDot id={id} side={side} />}
        {name && <span className="truncate">{name}</span>}
      </span>
      {mid ?? (
        <span aria-hidden className="block h-1.5 overflow-hidden rounded-full bg-line-2">
          {bar !== null && bar !== undefined && (
            <i className="block h-full rounded-full" style={{ width: `${bar}%`, background: fill }} />
          )}
        </span>
      )}
      <span className="text-end font-medium tabular-nums">{children}</span>
      {sub && <span className="col-span-3 text-ink-2">{sub}</span>}
    </>
  );
}

/** The one state line for a shop whose value is not available, with the API's reason. */
function State({ id, side, children }: { id: string; side: 0 | 1; children: ReactNode }) {
  return (
    <span className="col-span-3 rounded-ctl bg-surface-2 px-2.5 py-1.5 text-ink-2">
      <RetailerDot id={id} side={side} /> {children}
    </span>
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
      <PairTile k={t('pairs')} href={href} tone="bg-lav" sub={t('pairsOf', { base, other })}>
        <Row>{s ? formatCount(s.n, locale) : none}</Row>
      </PairTile>
      <PairTile
        k={t('index')}
        href={href}
        tone="bg-sky"
        sub={s ? t('indexOf', { other, base, n: formatCount(s.n, locale) }) : undefined}
      >
        <Row>
          {s && Number.isFinite(gap) ? (
            // The sign stays in front of the number in Arabic too.
            <span
              dir="ltr"
              className={`inline-block ${gap > 0 ? 'text-blush-ink' : gap < 0 ? 'text-sky-ink' : ''}`}
            >
              {gap > 0 ? '+' : ''}
              {pct(s.medianGapPct, locale)}
            </span>
          ) : (
            none
          )}
        </Row>
      </PairTile>
      <PairTile
        k={t('cheaper')}
        href={href}
        tone="bg-mint"
        sub={s ? t('same', { n: formatCount(s.equalCount, locale) }) : undefined}
      >
        {s ? (
          <>
            <Row name={base}>{wins(s.cheaperCounts[pair.base], locale)}</Row>
            <Row name={other}>{wins(s.cheaperCounts[pair.other], locale)}</Row>
          </>
        ) : (
          <Row>{none}</Row>
        )}
      </PairTile>
    </dl>
  );
}

/** A retailer's wins; a count the API did not send is unknown, shown as a dash, never 0. */
const wins = (n: number | undefined, locale: string) =>
  typeof n === 'number' ? formatCount(n, locale) : <None>–</None>;

function PairTile({
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
