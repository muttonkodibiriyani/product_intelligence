/**
 * Pure shaping of /summary for the landing widgets: no React, no ECharts, so it is unit-tested.
 * Values stay the API's decimal strings until a chart needs a coordinate.
 */
import { EMPTY, toSearch, type ExploreState } from '@/lib/explore';
import { EMPTY_PROMOTIONS, MIN_PCTS, toPromotionsSearch, type MinPct } from '@/lib/promotions';
import { num, type Summary } from '@/lib/api/summary';

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
  return ladder
    .map((r) => ({
      ...r,
      v: [num(r.min), num(r.p25), num(r.p50), num(r.p75), num(r.max)] as const,
    }))
    .filter((r) => r.v.every((x) => Number.isFinite(x) && x > 0) && r.v[0] <= r.v[4]);
}

/** Heatmap cells as [col, row, count]; the largest count sets the colour scale. */
export function heatCells(d: NonNullable<Summary['promoDepth']>) {
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
  name: string;
  value: number;
}

/** Categories for the treemap, largest first; one level deep, as /summary sends them. */
export function categoryNodes(mix: Summary['categoryMix']): TreeNode[] {
  return mix
    .filter((c) => c.category && c.n > 0)
    .map((c) => ({ name: c.category, value: c.n }))
    .sort((a, b) => b.value - a.value);
}

/** Histogram bins with their bounds kept as the API's strings, for labels and drill links. */
export function histBins(h: Summary['priceHist']) {
  return h.counts.flatMap((count, i) => {
    const lo = h.edges[i];
    const hi = h.edges[i + 1];
    return lo === undefined || hi === undefined ? [] : [{ lo, hi, count }];
  });
}

/** Scatter points [price, rating, reviews], dropping unplaceable ones. */
export function ratingPoints(r: Summary['ratingPrice']) {
  return r.points
    .map((p) => [num(p.price), num(p.rating), p.count] as [number, number, number])
    .filter(([x, y]) => x > 0 && Number.isFinite(y));
}

/** Product images come only from the retailer's image host, over https (image decision B). */
export const IMAGE_HOST = 'img-product.sephora.me';
export function imageSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && u.hostname === IMAGE_HOST ? u.toString() : null;
  } catch {
    return null;
  }
}

/** The freshness badge as /summary rates it, never guessed from the age alone. */
export function freshness(f: Summary['freshness']): 'fresh' | 'aging' | 'stale' | 'unknown' {
  return f.status === 'fresh' || f.status === 'aging' || f.status === 'stale' ? f.status : 'unknown';
}

export const WITHHELD_REASONS = ['capability_off', 'field_not_collected', 'cohort_too_small'] as const;

/**
 * The promotion sections, or why they are withheld. /summary nulls all three together and lists
 * "promotions" in `withheld`; either sign keeps every promotion widget off the landing, and
 * nothing indexes into them before this check.
 */
export function promotions(s: Pick<Summary, 'withheld' | 'promoSharePct' | 'promoDepth' | 'topDiscounts'>):
  | {
      measured: true;
      share: string;
      depth: NonNullable<Summary['promoDepth']>;
      top: NonNullable<Summary['topDiscounts']>;
    }
  | { measured: false; reason: string } {
  const w = s.withheld?.find((x) => x.section === 'promotions');
  if (w || s.promoSharePct === null || !s.promoDepth || !s.topDiscounts)
    return { measured: false, reason: w?.reason ?? 'field_not_collected' };
  return { measured: true, share: s.promoSharePct, depth: s.promoDepth, top: s.topDiscounts };
}

/**
 * Brand concentration from the brands /summary lists (the top 30 by priced products): each
 * brand's share of all priced products and the running total, largest first. The denominator is
 * `priced`, not `products`, which also counts unpriced products.
 */
export function brandShare(brands: Summary['brandPrice'], priced: number) {
  if (!(priced > 0)) return [];
  let cum = 0;
  return [...brands]
    .filter((b) => b.n > 0)
    .sort((a, b) => b.n - a.n)
    .map((b) => {
      cum += b.n;
      return { brand: b.brand, n: b.n, share: (b.n / priced) * 100, cum: (cum / priced) * 100 };
    });
}
