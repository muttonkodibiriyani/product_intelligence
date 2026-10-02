import type { Schemas } from './api/types';
import { priceState } from './money';

type Card = Pick<Schemas['ProductCard'], 'gap' | 'prices' | 'priceFlags'>;

/**
 * What a product card says about a pair in one chip. Every value is the API's: the cheaper side
 * and the percentage come from `PairGap.gap`, the reason from `excludedReason`.
 *
 * - `cheaper`: one shop is cheaper by `pct` (the API's percentage, sign dropped).
 * - `same`: both shops charge the same.
 * - `sizes`: the shops sell different sizes, so the prices are not compared.
 * - `review`: a side's price is withheld as a placeholder (lib/money.ts `priceState`).
 * - `excluded`: any other reason the API gave for not counting the pair.
 *
 * `null` when there is nothing to say: no pair asked for, or the product is not sold at both
 * shops (the price lines already read "Not sold").
 */
export type Verdict =
  | { kind: 'cheaper'; retailer: string; pct: string }
  | { kind: 'same' }
  | { kind: 'sizes' }
  | { kind: 'review' }
  | { kind: 'excluded'; reason: Schemas['Excluded'] };

export function verdictOf(card: Card): Verdict | null {
  const g = card.gap;
  if (!g) return null;
  const review = [g.base, g.other].some(
    (id) =>
      id in card.prices &&
      priceState({ price: card.prices[id], priceFlag: card.priceFlags?.[id] }) === 'review',
  );
  if (review) return { kind: 'review' };
  if (g.gap) {
    if (g.gap.cheaper === 'equal') return { kind: 'same' };
    return {
      kind: 'cheaper',
      retailer: g.gap.cheaper === 'base' ? g.base : g.other,
      pct: g.gap.pct.replace(/^-/, ''),
    };
  }
  switch (g.excludedReason) {
    case null:
    case 'not_offered':
      return null;
    case 'size_mismatch':
    case 'size_unknown':
      return { kind: 'sizes' };
    default:
      return { kind: 'excluded', reason: g.excludedReason };
  }
}

/** The largest |pct| among the gaps, the scale every bar in one list is drawn against; 1 at least. */
export function gapScale(cards: readonly Pick<Schemas['ProductCard'], 'gap'>[]): number {
  return Math.max(1, ...cards.map((c) => Math.abs(Number(c.gap?.gap?.pct ?? 0)) || 0));
}

/**
 * The fill of a zero-centred gap bar, for `PairGap.gap`: which side of zero and how much of the
 * half width (0–50, as a percentage of the bar). The base shop cheaper is the good side (green),
 * the base dearer the bad side (red); the length is |pct| against `scale` (see `gapScale`).
 */
export function gapBar(gap: Schemas['Gap'], scale: number): { side: 'good' | 'bad'; width: number } | null {
  const pct = Number(gap.pct);
  if (!Number.isFinite(pct) || pct === 0) return null;
  return {
    side: gap.cheaper === 'base' ? 'good' : 'bad',
    width: Math.round(Math.min(Math.abs(pct) / scale, 1) * 50 * 10) / 10,
  };
}
