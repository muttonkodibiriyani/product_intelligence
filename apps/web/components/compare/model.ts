/**
 * Pure shaping of a /compare body for the page: who is cheaper, what was left out and why, and
 * the basket difference. No React, so it is unit-tested; every number comes from the API's own
 * counts and decimal strings, never recomputed from the rows on screen.
 */
import type { Money, Schemas } from '@/lib/api/types';

type PairRow = Schemas['PairRow'];
type CompareSummary = Schemas['CompareSummary'];
type Excluded = Schemas['Excluded'];

/** The reasons the page has plain words for, in the order the fold line lists them. */
export const EXCLUDED: readonly Excluded[] = [
  'size_mismatch',
  'size_unknown',
  'not_offered',
  'unpriced',
  'match_unreviewed',
  'match_not_exact',
  'match_rejected',
  'no_match',
  'early',
  'currency_mismatch',
];

/** A retailer's colour: the shop's own tone for the two the design names, else a series tone by side. */
export function retailerTone(id: string, side: 0 | 1): string {
  if (/^ulta(_|$)/.test(id)) return 'var(--color-ulta, #d1541c)';
  if (/^sephora(_|$)/.test(id)) return 'var(--color-sephora, #1d2129)';
  return side === 0 ? 'var(--color-series-a, #e07c9d)' : 'var(--color-series-b, #5e9ad4)';
}

/** Matched rows first (the API already sorts them widest gap first), then everything left out. */
export function splitRows(rows: readonly PairRow[]) {
  const matched = rows.filter((r): r is PairRow & { gap: Schemas['Gap'] } => r.counted && !!r.gap);
  const excluded = rows.filter((r) => !(r.counted && !!r.gap));
  return { matched, excluded };
}

/** The excluded rows tallied by reason, largest group first; an unknown reason lands in 'other'. */
export function excludedGroups(rows: readonly PairRow[]): { reason: Excluded | 'other'; n: number }[] {
  const n = new Map<Excluded | 'other', number>();
  for (const r of rows) {
    const k = r.excludedReason && EXCLUDED.includes(r.excludedReason) ? r.excludedReason : 'other';
    n.set(k, (n.get(k) ?? 0) + 1);
  }
  const order = (k: Excluded | 'other') => (k === 'other' ? EXCLUDED.length : EXCLUDED.indexOf(k));
  return [...n.entries()]
    .map(([reason, count]) => ({ reason, n: count }))
    .sort((a, b) => b.n - a.n || order(a.reason) - order(b.reason));
}

/** Which side of a row carries a price: 'base', 'other', or null when neither (or both) does. */
export function onlySide(r: Pick<PairRow, 'basePrice' | 'otherPrice'>): 'base' | 'other' | null {
  if (r.basePrice && !r.otherPrice) return 'base';
  if (!r.basePrice && r.otherPrice) return 'other';
  return null;
}

/** The side without a price, for an unpriced row; null when both or neither have one. */
export function unpricedSide(r: Pick<PairRow, 'basePrice' | 'otherPrice'>): 'base' | 'other' | null {
  const s = onlySide(r);
  return s === 'base' ? 'other' : s === 'other' ? 'base' : null;
}

export type Verdict =
  | { kind: 'allSame'; n: number }
  | { kind: 'tie'; k: number; n: number; equal: number }
  | { kind: 'lead'; leader: 'base' | 'other'; k: number; trailing: number; equal: number; n: number };

/** Who wins more often on the matched products, from the API's own counts. */
export function verdict(s: CompareSummary, base: string, other: string): Verdict {
  const a = s.cheaperCounts[base] ?? 0;
  const b = s.cheaperCounts[other] ?? 0;
  const equal = s.equalCount;
  if (a === 0 && b === 0) return { kind: 'allSame', n: s.n };
  if (a === b) return { kind: 'tie', k: a, n: s.n, equal };
  return a > b
    ? { kind: 'lead', leader: 'base', k: a, trailing: b, equal, n: s.n }
    : { kind: 'lead', leader: 'other', k: b, trailing: a, equal, n: s.n };
}

/**
 * other − base of two API money values, on their integer minor units (no floating point), as a
 * money value in the same currency; null across currencies or when either amount is not an integer
 * count of minor units.
 */
export function minus(other: Money, base: Money): Money | null {
  if (other.currency !== base.currency) return null;
  if (!Number.isInteger(other.minor) || !Number.isInteger(base.minor)) return null;
  const minor = other.minor - base.minor;
  const decimals = (base.amount.split('.')[1] ?? '').length;
  const abs = Math.abs(minor)
    .toString()
    .padStart(decimals + 1, '0');
  const amount =
    (minor < 0 ? '-' : '') + (decimals ? `${abs.slice(0, -decimals)}.${abs.slice(-decimals)}` : abs);
  return { amount, currency: base.currency, minor };
}

/** Sign of an API decimal string: 1 above zero, -1 below, 0 at zero (or unreadable). */
export function sign(v: string | null | undefined): -1 | 0 | 1 {
  if (!v || !/^-?\d+(\.\d+)?$/.test(v)) return 0;
  const n = Number(v);
  return n > 0 ? 1 : n < 0 ? -1 : 0;
}

/** |pct| as a share of the widest matched gap, 0…1, for the zero-centred bar beside each amount. */
export function gapShare(pct: string, rows: readonly { gap: { pct: string } }[]): number {
  const abs = (v: string) => Math.abs(Number(v)) || 0;
  const max = rows.reduce((m, r) => Math.max(m, abs(r.gap.pct)), 0);
  return max > 0 ? Math.min(1, abs(pct) / max) : 0;
}
