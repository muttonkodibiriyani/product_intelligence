/**
 * Pure shaping of /summary for the landing widgets: no React, no ECharts, so it is unit-tested.
 * Values stay the API's decimal strings until a chart needs a coordinate.
 */
import { EMPTY, toSearch, type ExploreState } from '@/lib/explore';
import { EMPTY_PROMOTIONS, MIN_PCTS, toPromotionsSearch, type MinPct } from '@/lib/promotions';
import { num, type Measured, type Summary } from '@/lib/api/summary';
import type { CaveatView } from '@/lib/api/types';

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

/** Scatter points [price, rating, reviews], dropping unplaceable ones. */
export function ratingPoints(r: Summary['ratingPrice']) {
  if (!r) return [];
  return r.points
    .map((p) => [num(p.price), num(p.rating), p.count] as [number, number, number])
    .filter(([x, y]) => x > 0 && Number.isFinite(y));
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
