import type { Schemas } from './api/types';

export type Insights = Schemas['Insights'];
export type SizeGap = Schemas['SizeGap'];
export type BrandPolicy = Schemas['BrandPolicy'];
export type Policy = Schemas['Policy'];
export type Ladder = Schemas['Ladder'];
export type LadderStep = Schemas['LadderStep'];
export type Stockouts = Schemas['Stockouts'];

/** Size-trap examples listed per shop; the API lists up to twelve, steepest first. */
export const TRAPS_SHOWN = 5;
/** Brands shown per policy column before the rest fold into a count. */
export const BRANDS_SHOWN = 8;

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

/** Is every listing observed in a stock state out of stock? Said as counts, never as a share. */
export const allObservedOut = (b: Schemas['BrandStock']): boolean =>
  b.observed > 0 && b.outOfStock === b.observed;

/** The pair's shops only, in pair order: the page never ranks shops against each other. */
export function forPair<T extends { retailer: string }>(
  rows: readonly T[],
  base: string,
  other: string,
): T[] {
  return [base, other].flatMap((id) => rows.filter((r) => r.retailer === id));
}
