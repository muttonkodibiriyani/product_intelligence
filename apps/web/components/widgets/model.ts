/**
 * Pure shaping of /summary for the landing widgets: no React, no ECharts, so it is unit-tested.
 * Values stay the API's decimal strings until a chart needs a coordinate.
 */
import { EMPTY, toSearch, type ExploreState } from '@/lib/explore';
import { EMPTY_PROMOTIONS, MIN_PCTS, toPromotionsSearch, type MinPct } from '@/lib/promotions';
import { num, type Measured, type Summary } from '@/lib/api/summary';
import type { CaveatView, Envelope, Schemas } from '@/lib/api/types';
import { ApiError } from '@/lib/api/client';
import { EMPTY_COMPARE, toCompareSearch, type GroupBy } from '@/lib/compare';
import { isValidAmount, isValidPrice } from '@/lib/money';

/** An amount in the user's language with Latin digits, like `formatMoney`; whole units on axes. */
export function amount(v: string, currency: string, locale: string, whole = false): string {
  if (!/^-?\d+(\.\d+)?$/.test(v)) return v;
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-AE' : 'en-AE', {
    style: 'currency',
    currency: currency || 'AED',
    numberingSystem: 'latn',
    ...(whole ? { maximumFractionDigits: 0, minimumFractionDigits: 0 } : {}),
  }).format(v as Intl.StringNumericLiteral);
}

/** A percentage string from the API ("23.4") as "23.4%", in Latin digits. */
export function pct(v: string | null | undefined, locale: string): string {
  if (v === null || v === undefined || !/^-?\d+(\.\d+)?$/.test(v)) return '–';
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-AE' : 'en-GB', {
    style: 'percent',
    numberingSystem: 'latn',
    maximumFractionDigits: 1,
  }).format(Number(v) / 100);
}

/** Links behind the marks, so every number on the landing opens the list it was counted from. */
export const exploreHref = (locale: string, s: Partial<ExploreState>) =>
  `/${locale}/explore/${toSearch({ ...EMPTY, ...s })}`;

export const promotionsHref = (locale: string, s: { category?: string; minPct?: string }) =>
  `/${locale}/promotions/${toPromotionsSearch({
    ...EMPTY_PROMOTIONS,
    category: s.category ? [s.category] : [],
    minPct: (MIN_PCTS as readonly string[]).includes(s.minPct ?? '') ? (s.minPct as MinPct) : '',
  })}`;

/** The comparison page for a pair, optionally grouped or narrowed to one category or brand. */
export const compareHref = (
  locale: string,
  s: { base: string; other: string; groupBy?: GroupBy | null; category?: string; brand?: string },
) =>
  `/${locale}/compare/${toCompareSearch({
    ...EMPTY_COMPARE,
    base: s.base,
    other: s.other,
    groupBy: s.groupBy ?? null,
    category: s.category ? [s.category] : [],
    brand: s.brand ? [s.brand] : [],
  })}`;

/** The lower bound of a discount band label ("20-30", "20–30%", "50+"), or '' if it has none. */
export function bandFloor(label: string): string {
  const m = /^\s*(\d{1,3})/.exec(label);
  return m ? m[1]! : '';
}

/** Ladder rows with numbers, dropping any the chart could not place (and any non-positive price on a log axis). */
export function ladderRows(ladder: Summary['ladder']) {
  return (ladder ?? [])
    .map((r) => ({
      ...r,
      v: [
        num(r.min.amount),
        num(r.p25.amount),
        num(r.p50.amount),
        num(r.p75.amount),
        num(r.max.amount),
      ] as const,
    }))
    .filter((r) => r.v.every((x) => Number.isFinite(x) && x > 0) && r.v[0] <= r.v[4]);
}

/** Heatmap cells as [col, row, count]; the largest count sets the colour scale. */
export function heatCells(d: Measured<'promoDepth'>) {
  const cells: [number, number, number][] = [];
  let max = 0;
  d.category.forEach((_, ri) =>
    d.bands.forEach((_, ci) => {
      const v = d.cells[ri]?.[ci] ?? 0;
      max = Math.max(max, v);
      cells.push([ci, ri, v]);
    }),
  );
  return { cells, max };
}

export interface TreeNode {
  /** The category's own name, the last step of its path: what the tile shows. */
  name: string;
  /** The whole path, for the tooltip; its first step is the category code the drill filters on. */
  trail: string[];
  value: number;
}

/** Categories for the treemap, largest first: one tile per path /summary counts. */
export function categoryNodes(mix: Summary['categoryMix']): TreeNode[] {
  return (mix ?? [])
    .filter((c) => c.category.length > 0 && c.n > 0)
    .map((c) => ({ name: c.category[c.category.length - 1]!, trail: c.category, value: c.n }))
    .sort((a, b) => b.value - a.value);
}

/**
 * The explorer for a tile's category. The API filters on the category code, the path's first step
 * (#111), so a leaf like "Liquid Lipstick" would open an empty list.
 */
export function categoryNodeHref(locale: string, n: TreeNode): string {
  return exploreHref(locale, { category: n.trail.slice(0, 1) });
}

/** Histogram bins with their bounds kept as the API's strings, for labels and drill links. */
export function histBins(h: Summary['priceHist']) {
  if (!h) return [];
  return h.counts.flatMap((count, i) => {
    const lo = h.edges[i];
    const hi = h.edges[i + 1];
    return lo === undefined || hi === undefined ? [] : [{ lo, hi, count }];
  });
}

/**
 * The /compare gap histogram, one entry per bin as sent: bin 0 is below edges[0] (`lo` null), bin k
 * is [edges[k-1], edges[k]), the last is at or above the top edge (`hi` null). The bins have unequal
 * widths, so each is drawn as its own bar and named by its range. A body whose counts don't fit
 * its edges is not drawn at all.
 */
export interface GapBin {
  lo: string | null;
  hi: string | null;
  count: number;
}
export function gapHistBins(h: Schemas['GapHistogram'] | null | undefined): GapBin[] {
  if (!h || h.edges.length === 0 || h.counts.length !== h.edges.length + 1) return [];
  const last = h.edges.length;
  return h.counts.map((count, i) => ({
    lo: i === 0 ? null : h.edges[i - 1]!,
    hi: i === last ? null : h.edges[i]!,
    count,
  }));
}

/** Which side a bin leans to: above zero the other retailer is dearer, below it cheaper. */
export function gapBinSign(b: GapBin): -1 | 0 | 1 {
  if (b.lo === null) return -1;
  if (b.hi === null) return 1;
  const mid = num(b.lo) + num(b.hi);
  return mid > 0 ? 1 : mid < 0 ? -1 : 0;
}

/** Scatter points [price, rating, reviews], dropping unplaceable ones. */
export function ratingPoints(r: Summary['ratingPrice']) {
  if (!r) return [];
  return (
    r.points
      // A placeholder price (0.01 or less) is not a point.
      .filter((p) => isValidAmount(p.price))
      .map((p) => [num(p.price), num(p.rating), p.count] as [number, number, number])
      .filter(([x, y]) => x > 0 && Number.isFinite(y))
  );
}

/**
 * Product images are hotlinked, never copied, and only from each retailer's own image host, over
 * https (image decision B; media.alshaya.com only keeps the owner's ulta_ae view live). Each host is
 * credited with a link to its owner's public home page.
 */
export const IMAGE_OWNERS = {
  'img-product.sephora.me': { name: 'Sephora', home: 'https://www.sephora.me' },
  'media.alshaya.com': { name: 'Ulta Beauty', home: 'https://www.ulta.ae' },
} as const;
export type ImageHost = keyof typeof IMAGE_OWNERS;
/** The retailer each host serves; a URL is shown only for its own retailer. */
const HOST_RETAILER: Record<ImageHost, string> = {
  'img-product.sephora.me': 'sephora_me',
  'media.alshaya.com': 'ulta_ae',
};

/** The image host of an allowed URL (https, a listed host, no credentials), else null. */
export function imageHost(url: string | null | undefined, retailer?: string): ImageHost | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' || u.username || u.password || !Object.hasOwn(IMAGE_OWNERS, u.hostname))
      return null;
    const host = u.hostname as ImageHost;
    return retailer && HOST_RETAILER[host] !== retailer ? null : host;
  } catch {
    return null;
  }
}

/** The URL to render, or null for a placeholder. With a retailer, only that retailer's host. */
export function imageSrc(url: string | null | undefined, retailer?: string): string | null {
  return imageHost(url, retailer) ? new URL(url!).toString() : null;
}

/**
 * The freshness badge as /summary rates it, never guessed from the age alone. A `snapshot` is an
 * imported retailer: its cutoff is the import date, not a capture date, so it is never aged.
 */
export function freshness(f: Summary['freshness']): 'fresh' | 'aging' | 'stale' | 'snapshot' | 'unknown' {
  return f.status === 'fresh' || f.status === 'aging' || f.status === 'stale' || f.status === 'snapshot'
    ? f.status
    : 'unknown';
}

/**
 * When a retailer's data was imported rather than collected, from the API's
 * `snapshot_import_date` caveat; null for a collected retailer or a caveat without a date.
 */
export function importedOn(caveats: readonly CaveatView[], retailer: string): string | null {
  const c = caveats.find((x) => x.code === 'snapshot_import_date' && x.params.retailer === retailer);
  return c && /^\d{4}-\d{2}-\d{2}$/.test(c.params.date ?? '') ? c.params.date! : null;
}

/** Whether the API says a retailer's product count may include parent listings. */
export const hasParents = (caveats: readonly CaveatView[], retailer: string) =>
  caveats.some((x) => x.code === 'parent_listings_included' && x.params.retailer === retailer);

/** The reasons the landing words itself; any other reads as a generic "not measured". */
export const WITHHELD_REASONS = [
  'capability_off',
  'field_not_collected',
  'cohort_too_small',
  'retailer_blocked',
  'retailer_partial',
  'was_price_unverified',
] as const;

/** Why a section is withheld, if /summary says it is. */
export const withheldReason = (
  s: Pick<Summary, 'withheld'>,
  section: Summary['withheld'][number]['section'],
) => s.withheld.find((w) => w.section === section)?.reason;

/**
 * The promotion sections, or why they are withheld. /summary nulls all three together and lists
 * "promotions" in `withheld`; either sign keeps every promotion widget off the landing, and
 * nothing indexes into them before this check.
 */
export function promotions(s: Pick<Summary, 'withheld' | 'promoSharePct' | 'promoDepth' | 'topDiscounts'>):
  | {
      measured: true;
      share: string;
      depth: Measured<'promoDepth'>;
      top: Measured<'topDiscounts'>;
    }
  | { measured: false; reason: string } {
  const why = withheldReason(s, 'promotions');
  if (why || s.promoSharePct === null || !s.promoDepth || !s.topDiscounts)
    return { measured: false, reason: why ?? 'field_not_collected' };
  return { measured: true, share: s.promoSharePct, depth: s.promoDepth, top: s.topDiscounts };
}

/**
 * Brand concentration from the brands /summary lists (the top 30 by priced products): each
 * brand's share of all priced products and the running total, largest first. The denominator is
 * `priced`, not `products`, which also counts unpriced products.
 */
export function brandShare(brands: Summary['brandPrice'], priced: number | null) {
  if (!brands || !priced || !(priced > 0)) return [];
  let cum = 0;
  return [...brands]
    .filter((b) => b.n > 0)
    .sort((a, b) => b.n - a.n)
    .map((b) => {
      cum += b.n;
      return { brand: b.brand, n: b.n, share: (b.n / priced) * 100, cum: (cum / priced) * 100 };
    });
}

/** Retailers the dashboard reports on: collected or partly collected, never blocked or pending. */
export function activeRetailers(meta: Pick<Schemas['MetaView'], 'retailers'> | null | undefined): string[] {
  return (meta?.retailers ?? [])
    .filter((r) => r.status === 'supported' || r.status === 'partial')
    .map((r) => r.id);
}

/**
 * Only the caveats about the retailers in a request. On API < 1.5.2 an imported retailer's
 * caveats are not scoped, so an Ulta caveat can arrive on a Sephora-only request; a caveat that
 * names another retailer is dropped here. One without a retailer applies to the whole response.
 */
export function scopedCaveats(caveats: readonly CaveatView[], retailers: readonly string[]): CaveatView[] {
  return caveats.filter((c) => !c.params?.retailer || retailers.includes(c.params.retailer));
}

type IndexPoint = Schemas['IndexPoint'];

/**
 * The index points a trend line may draw: only when the API says a trend exists AND at least two
 * days carry an index (owner rule: no line over time until real multi-day history exists). Null
 * means "no line": the card says history begins once nightly collection runs.
 */
export function trendPoints(
  index: Pick<Schemas['PriceIndex'], 'points' | 'trendAvailable'> | null | undefined,
): (IndexPoint & { index: string })[] | null {
  if (!index?.trendAvailable) return null;
  const pts = index.points.filter((p): p is IndexPoint & { index: string } => p.index !== null);
  return pts.length >= 2 ? pts : null;
}

type PairRow = Schemas['PairRow'];

/** Counted pairs with two real prices, widest gap first: the rows a head-to-head chart may plot. */
export function gapRows(rows: readonly PairRow[], top = 10) {
  return rows
    .filter(
      (r): r is PairRow & { gap: Schemas['Gap'] } =>
        r.counted &&
        !!r.gap &&
        isValidPrice(r.basePrice) &&
        isValidPrice(r.otherPrice) &&
        Number.isFinite(num(r.gap.pct)),
    )
    .sort((a, b) => Math.abs(num(b.gap.pct)) - Math.abs(num(a.gap.pct)))
    .slice(0, top);
}

/**
 * A group whose summary carries a count for both retailers; one with a missing count is not
 * drawn (a missing count is unknown, never 0 wins).
 */
type Counted = Schemas['Group'] & { summary: Schemas['CompareSummary'] };
const counted =
  (base: string, other: string) =>
  (g: Schemas['Group']): g is Counted =>
    !!g.summary &&
    typeof g.summary.cheaperCounts[base] === 'number' &&
    typeof g.summary.cheaperCounts[other] === 'number';

/** Who is cheaper per group, for the heatmap: [column, row, count], columns base / same / other. */
export function cheaperCells(groups: readonly Schemas['Group'][], base: string, other: string) {
  const ok = counted(base, other);
  const measured = groups.filter(ok);
  const thin = groups.filter((g) => !ok(g));
  const cells: [number, number, number][] = [];
  let max = 0;
  measured.forEach((g, ri) => {
    const s = g.summary;
    [s.cheaperCounts[base]!, s.equalCount, s.cheaperCounts[other]!].forEach((n, ci) => {
      max = Math.max(max, n);
      cells.push([ci, ri, n]);
    });
  });
  return { rows: measured, thin, cells, max };
}

/** One cell of the category × brand heatmap: who is cheaper how often on the pairs in it. */
export interface CrossCell {
  col: number;
  row: number;
  n: number;
  baseWins: number;
  otherWins: number;
  equal: number;
  /** (base wins − other wins) / n, −1…1; null under the cohort minimum: "too few pairs", never 0. */
  value: number | null;
}

/**
 * Who is cheaper per category (rows) and brand (columns), computed from /compare's counted rows:
 * only for a response that is not truncated, so every pair is in. The busiest categories and
 * brands by pairs are kept; a category is the first step of the row's path, like the treemap.
 */
export function crossCells(
  rows: readonly PairRow[],
  opts: { min?: number; maxRows?: number; maxCols?: number } = {},
) {
  const { min = 5, maxRows = 12, maxCols = 8 } = opts;
  const counted = rows.filter(
    (r): r is PairRow & { gap: Schemas['Gap'] } =>
      r.counted && !!r.gap && isValidPrice(r.basePrice) && isValidPrice(r.otherPrice),
  );
  const top = (key: (r: PairRow) => string, k: number) => {
    const n = new Map<string, number>();
    for (const r of counted) n.set(key(r), (n.get(key(r)) ?? 0) + 1);
    return [...n.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, k)
      .map(([v]) => v);
  };
  const cat = (r: PairRow) => r.category[0] ?? '';
  const cats = top(cat, maxRows);
  const brands = top((r) => r.brand, maxCols);
  const cells: CrossCell[] = [];
  let pairs = 0;
  cats.forEach((c, row) =>
    brands.forEach((b, col) => {
      const inCell = counted.filter((r) => cat(r) === c && r.brand === b);
      if (inCell.length === 0) return;
      const baseWins = inCell.filter((r) => r.gap.cheaper === 'base').length;
      const otherWins = inCell.filter((r) => r.gap.cheaper === 'other').length;
      const equal = inCell.length - baseWins - otherWins;
      const n = inCell.length;
      pairs += n;
      cells.push({
        col,
        row,
        n,
        baseWins,
        otherWins,
        equal,
        value: n >= min ? (baseWins - otherWins) / n : null,
      });
    }),
  );
  return { cats, brands, cells, pairs, thin: cells.filter((c) => c.value === null).length };
}

/** Each group's cheaper shares for the fallback bars: base / same / other as fractions of its pairs. */
export function cheaperShares(groups: readonly Schemas['Group'][], base: string, other: string) {
  return groups
    .filter(counted(base, other))
    .filter((g) => g.summary.n > 0)
    .map((g) => {
      const s = g.summary;
      const b = s.cheaperCounts[base]!;
      const o = s.cheaperCounts[other]!;
      return {
        key: g.key,
        n: s.n,
        base: b / s.n,
        same: s.equalCount / s.n,
        other: o / s.n,
        baseN: b,
        otherN: o,
        sameN: s.equalCount,
      };
    })
    .sort((a, b) => b.base - a.base || b.n - a.n);
}

/** What a head-to-head query can be in; `ready` carries the body and its envelope. */
export type PairState<T> =
  | { kind: 'loading' }
  | { kind: 'error'; error: unknown; retry: () => void }
  | { kind: 'empty'; env: Envelope<T> | null }
  | { kind: 'ready'; data: T; env: Envelope<T> };

/**
 * Folds a query's result into one state. A body without the arrays a chart draws from is `empty`,
 * never handed to a chart. With `notFoundIsEmpty`, a 404 / `not_found` is also `empty`: the
 * resource does not exist in this dataset yet, which is no data, not a failure. Every other
 * failure (5xx, network) stays an error with a retry.
 */
export function pairState<T>(
  q: { data?: Envelope<T>; isError: boolean; error: unknown; refetch: () => unknown },
  shaped: (d: T) => boolean,
  opts: { notFoundIsEmpty?: boolean } = {},
): PairState<T> {
  if (q.isError && !q.data) {
    const e = q.error;
    if (opts.notFoundIsEmpty && e instanceof ApiError && (e.code === 'not_found' || e.status === 404))
      return { kind: 'empty', env: null };
    return { kind: 'error', error: e, retry: () => void q.refetch() };
  }
  if (!q.data) return { kind: 'loading' };
  if (!q.data.data || q.data.status !== 'ok' || !shaped(q.data.data)) return { kind: 'empty', env: q.data };
  return { kind: 'ready', data: q.data.data, env: q.data };
}
