import type { Schemas } from './api/types';

export type Insights = Schemas['Insights'];
export type SizeGap = Schemas['SizeGap'];
export type BrandPolicy = Schemas['BrandPolicy'];
export type Policy = Schemas['Policy'];
export type Ladder = Schemas['Ladder'];
export type LadderStep = Schemas['LadderStep'];
export type Stockouts = Schemas['Stockouts'];
export type ValuePicks = Schemas['ValuePicks'];
export type ValueCategory = Schemas['ValueCategory'];

/** Brands shown per policy column before the rest fold into a count. */
export const BRANDS_SHOWN = 8;
/** Per shop: partly out-of-stock brands shown. */
export const STOCK_BRANDS_SHOWN = 5;
/** Products listed under each value, size-step and discount card. */
export const CARD_ITEMS = { value: 3, size: 3, promo: 4 } as const;
/** Discounts asked per shop: enough that dropping repeated variants still leaves CARD_ITEMS.promo. */
export const PROMOS_ASKED = 30;
/** The dataset's catch-all category: a typical price across unlike products means nothing. */
export const CATCH_ALL = 'other';
/**
 * Below this share (%) of a category's priced products being rated by enough shoppers, its picks
 * come from a small set; the card says so next to them.
 */
export const FEW_RATED_PCT = 25;

/** Reasons that mean the shop's feed does not carry the field at all. */
const NOT_COLLECTED: ReadonlySet<string> = new Set(['capability_off', 'field_not_collected']);
export const notCollected = (reason: string | null | undefined): boolean =>
  !!reason && NOT_COLLECTED.has(reason);

/** The policy columns, left to right: the other shop cheaper, parity, the base shop cheaper. */
export const POLICY_ORDER: readonly Policy[] = ['other_cheaper', 'parity', 'base_cheaper'];

const num = (v: string): number => Number(v);

/** Sizes in measure order (unit, then value), so the chart reads small to large. */
export function sizesInOrder(sizes: readonly SizeGap[]): SizeGap[] {
  return [...sizes].sort((a, b) => a.unit.localeCompare(b.unit) || num(a.value) - num(b.value));
}

/**
 * The size the other shop undercuts most: the most negative median gap among sizes where it is
 * cheaper on more pairs than the base. Null when it undercuts on none.
 */
export function deepestUndercut(sizes: readonly SizeGap[]): SizeGap | null {
  let best: SizeGap | null = null;
  for (const s of sizes) {
    if (num(s.medianGapPct) >= 0 || s.otherCheaper <= s.baseCheaper) continue;
    if (!best || num(s.medianGapPct) < num(best.medianGapPct)) best = s;
  }
  return best;
}

/** Brands by policy label; `mixed` brands are only counted. Each column keeps the API's order. */
export function policyColumns(brands: readonly BrandPolicy[]): Record<Policy, BrandPolicy[]> {
  const out: Record<Policy, BrandPolicy[]> = { other_cheaper: [], parity: [], base_cheaper: [], mixed: [] };
  for (const b of brands) out[b.policy].push(b);
  return out;
}

/** The half-width share (0–100) a gap's bar takes on a diverging axis scaled to `max` %. */
export function barPct(gapPct: string, max: number): number {
  if (max <= 0) return 0;
  return Math.min(100, (Math.abs(num(gapPct)) / max) * 100);
}

/** The scale for a diverging chart: the largest absolute gap, at least 1 so 0 % still draws. */
export const gapScale = (gaps: readonly string[]): number =>
  Math.max(1, ...gaps.map((g) => Math.abs(num(g))));

/**
 * Variants listed under one name (shades, sizes) shown once: the first of each brand and name, in
 * the order given, compared without case or extra spaces.
 */
export function oncePerName<T extends { brand: string; name: string }>(items: readonly T[]): T[] {
  const seen = new Set<string>();
  const key = (v: string) => v.trim().replace(/\s+/g, ' ').toLocaleLowerCase('en');
  return items.filter((i) => {
    const k = `${key(i.brand)}\u0000${key(i.name)}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

/** A shop's value categories as shown: the API's order, without the catch-all. */
export const valueCategories = (v: ValuePicks): ValueCategory[] =>
  v.categories.filter((c) => c.category !== CATCH_ALL);

/** Are this category's picks drawn from few rated products (see FEW_RATED_PCT)? */
export const fewRated = (c: Pick<ValueCategory, 'rated' | 'priced'>): boolean =>
  c.priced > 0 && c.rated * 100 < c.priced * FEW_RATED_PCT;

/** A price per ml or g: an exact decimal string in a currency, not a priced Money. */
export type UnitAmount = { amount: string; currency: string };

/**
 * The typical price per unit of a per-unit category (fragrance), in the shelf median's currency:
 * the unit with the most priced offers. Null for a shelf-price category, or when no unit has a
 * median, so the line falls back to the shelf price it can show.
 */
export const perUnitMedian = (c: ValueCategory): { median: UnitAmount; unit: string } | null => {
  if (c.basis !== 'per_unit') return null;
  const best = [...c.unitMedians].sort((x, y) => y.n - x.n)[0];
  return best ? { median: { amount: best.median, currency: c.median.currency }, unit: best.unit } : null;
};

/** A pick's size and price per unit (in the pick's currency), when the API sends them. */
export const pickSize = (
  p: Schemas['ValuePick'],
): { size: { value: string; unit: string } | null; unitPrice: UnitAmount | null } => {
  const size = p.sizeValue && p.sizeUnit ? { value: p.sizeValue, unit: p.sizeUnit } : null;
  return {
    size,
    unitPrice: size && p.unitPrice ? { amount: p.unitPrice, currency: p.price.currency } : null,
  };
};

/** The rating floor on a five-point scale, from the API's percentage of a scale ("90.0" -> "4.5"). */
export const ratingOutOfFive = (pct: string): string => String(Math.round(Number(pct) * 5) / 100);

/** Every unordered pair of shops once, in the shops' order: the cross-shop price checks. */
export function shopPairs(ids: readonly string[]): { base: string; other: string }[] {
  return ids.flatMap((base, i) => ids.slice(i + 1).map((other) => ({ base, other })));
}

/** The shop the URL picks (`?shop=`), when it is one of the collected shops; else all of them. */
export function pickedShop(sp: URLSearchParams, active: readonly string[]): string | null {
  const s = sp.get('shop');
  return s && active.includes(s) ? s : null;
}

/** The first API version that serves Insights with stock totals and value picks (API 1.23.0; #265's 1.22.0 has neither). */
export const INSIGHTS_API = '1.23.0';

/** Is a dotted API version at least `min`? Numeric per part, so 1.17.0 > 1.9.9. */
export function apiAtLeast(version: string, min: string): boolean {
  const a = version.split('.').map(Number);
  const b = min.split('.').map(Number);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0);
    if (Number.isNaN(d)) return false;
    if (d !== 0) return d > 0;
  }
  return true;
}

/**
 * Does the live API serve Insights? Read from /meta's apiVersion, which every response carries, so
 * the page never has to call a route an older API lacks. Undefined until /meta has answered.
 */
export const insightsServed = (meta: { meta: { apiVersion: string } } | undefined): boolean | undefined =>
  meta ? apiAtLeast(meta.meta.apiVersion, INSIGHTS_API) : undefined;

/**
 * A brand as written for display: an all-caps word longer than four letters is title-cased
 * ("KYLIE COSMETICS" → "Kylie Cosmetics"); short all-caps acronyms (YSL, NYX, MAC) and mixed
 * forms (e.l.f., ULTA's "ULTA Beauty") keep their case.
 */
export function displayBrand(brand: string): string {
  return brand
    .split(' ')
    .map((w) => {
      const letters = w.match(/\p{L}/gu) ?? [];
      const caps =
        letters.length > 4 &&
        letters.every((c) => c === c.toLocaleUpperCase('en') && c !== c.toLocaleLowerCase('en'));
      return caps ? w.slice(0, 1) + w.slice(1).toLocaleLowerCase('en') : w;
    })
    .join(' ');
}

/** A count of a total as a percentage with one decimal ("6.4"), exact integer rounding; null without a total. */
export function sharePct(part: number, total: number): string | null {
  if (!(total > 0) || part < 0 || part > total) return null;
  return (Math.round((part * 1000) / total) / 10).toFixed(1);
}

/** One shop in a card's chart: a share or a percentage to draw, or a note in place of a bar. */
export type BarRow = { id: string; value: number | null };

/**
 * Bar lengths (0–100) for a card's chart, scaled to its largest value so the longest bar fills the
 * track; a row without a value (a note) has none, a negative value draws as 0.
 */
export function barWidths(rows: readonly BarRow[]): Map<string, number> {
  const max = Math.max(0, ...rows.map((r) => r.value ?? 0));
  const out = new Map<string, number>();
  for (const r of rows) {
    if (r.value === null) continue;
    out.set(r.id, max > 0 ? (Math.max(0, r.value) / max) * 100 : 0);
  }
  return out;
}

/**
 * A shop's value picks against the listings that could be picked: those with enough ratings in
 * the categories listed, so a large catalogue does not read as better value by size alone.
 */
export function valueShare(v: ValuePicks): { picks: number; rated: number; pct: string | null } {
  const cats = valueCategories(v);
  const picks = cats.reduce((a, c) => a + c.picks, 0);
  const rated = cats.reduce((a, c) => a + c.rated, 0);
  return { picks, rated, pct: sharePct(picks, rated) };
}

/** The shop the cards are about first, then the others in their order. */
export const focusFirst = (focus: string, shops: readonly string[]): string[] => [
  focus,
  ...shops.filter((s) => s !== focus),
];
