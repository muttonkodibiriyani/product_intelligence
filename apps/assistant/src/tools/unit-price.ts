/**
 * Price per unit (per ml or per g) from what the API serves: each product card's listed price
 * per retailer and its pack size as published (`size: {value, unit}`). The division is exact
 * decimal arithmetic, rounded half away from zero to `UNIT_PRICE_SCALE` places. Only metric
 * units are used: L, cl, kg and mg convert to ml or g by exact powers of ten. A product with no
 * size, a non-metric unit (oz, fl oz, pieces) or no price is excluded and counted, never
 * estimated.
 *
 * The card's `size` is one offer's measure, so it is applied only where it provably holds:
 * - a product priced at one retailer; or
 * - a product priced at exactly the two retailers of its `gap` pair, with a counted gap (no
 *   excluded reason), which pi_metrics gives only to a reviewed exact same-size match.
 * Any other multi-retailer product is excluded as `sizeUnproven` (offers can differ in size).
 * Rows carry their currency and are ranked within one measure and one currency, never across.
 */
import { DECIMAL_TEXT, type Decimal, parseDecimal } from "../guard/decimal.js";
import type { ToolView } from "./types.js";

export const UNIT_PRICE_SCALE = 4;

export type Measure = "ml" | "g";

/** Published unit (lower-cased, trimmed) → base unit and exact factor. */
const UNITS: Readonly<Record<string, { readonly per: Measure; readonly factor: string }>> = {
  ml: { per: "ml", factor: "1" },
  cl: { per: "ml", factor: "10" },
  l: { per: "ml", factor: "1000" },
  g: { per: "g", factor: "1" },
  kg: { per: "g", factor: "1000" },
  mg: { per: "g", factor: "0.001" },
};

function multiply(a: Decimal, b: Decimal): Decimal {
  return { units: a.units * b.units, scale: a.scale + b.scale };
}

/** a / b (both > 0), rounded half away from zero to `scale` places, as decimal text. */
export function divide(a: Decimal, b: Decimal, scale: number): string {
  const numerator = a.units * 10n ** BigInt(b.scale + scale);
  const denominator = b.units * 10n ** BigInt(a.scale);
  const units = (2n * numerator + denominator) / (2n * denominator);
  const digits = units.toString().padStart(scale + 1, "0");
  return scale === 0 ? digits : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
}

function positive(text: unknown): Decimal | null {
  if (typeof text !== "string" || !DECIMAL_TEXT.test(text)) return null;
  const value = parseDecimal(text);
  return value.units > 0n ? value : null;
}

interface Row {
  readonly id: string;
  readonly brand: unknown;
  readonly retailer: string;
  readonly price: string;
  readonly currency: string;
  readonly size: { readonly value: string; readonly unit: string };
  readonly perUnit: string;
  readonly per: Measure;
}

export interface UnitPriceInput {
  readonly per?: Measure | undefined;
  readonly order: "asc" | "desc";
  readonly rows: number;
}

function compareDecimalText(a: string, b: string): number {
  const [x, y] = [parseDecimal(a), parseDecimal(b)];
  const scale = Math.max(x.scale, y.scale);
  const left = x.units * 10n ** BigInt(scale - x.scale);
  const right = y.units * 10n ** BigInt(scale - y.scale);
  return left < right ? -1 : left > right ? 1 : 0;
}

interface Offer {
  readonly retailer: string;
  readonly price: Decimal;
  readonly text: string;
  readonly currency: string;
}

function offers(card: Record<string, unknown>): Offer[] {
  return Object.entries((card.prices ?? {}) as Record<string, unknown>).flatMap(
    ([retailer, money]) => {
      const { amount, currency } = (money ?? {}) as { amount?: unknown; currency?: unknown };
      const price = positive(amount);
      return price === null || typeof currency !== "string"
        ? []
        : [{ retailer, price, text: amount as string, currency }];
    },
  );
}

/** True if the card's one size provably applies to every priced offer (see the header). */
function sizeHolds(card: Record<string, unknown>, priced: readonly Offer[]): boolean {
  if (priced.length === 1) return true;
  if (priced.length !== 2) return false;
  const pair = card.gap as
    { base?: unknown; other?: unknown; gap?: unknown; excludedReason?: unknown } | null | undefined;
  if (!pair || pair.gap == null || pair.excludedReason != null) return false;
  const retailers = new Set(priced.map((offer) => offer.retailer));
  return (
    pair.base !== pair.other &&
    retailers.has(String(pair.base)) &&
    retailers.has(String(pair.other))
  );
}

/** The view over a /products page (`items`, `total`). */
export function unitPriceView(data: unknown, input: UnitPriceInput): ToolView {
  if (typeof data !== "object" || data === null || !("items" in data)) return { data };
  const { items, total } = data as { items: unknown; total: unknown };
  if (!Array.isArray(items)) return { data };
  const excluded = { noSize: 0, unitNotMetric: 0, otherMeasure: 0, noPrice: 0, sizeUnproven: 0 };
  const rows: Row[] = [];
  for (const card of items as Record<string, unknown>[]) {
    const size = card.size as { value?: unknown; unit?: unknown } | null | undefined;
    const value = positive(size?.value);
    if (value === null || typeof size?.unit !== "string") {
      excluded.noSize += 1;
      continue;
    }
    const unit = UNITS[size.unit.trim().toLowerCase()];
    if (unit === undefined) {
      excluded.unitNotMetric += 1;
      continue;
    }
    if (input.per !== undefined && unit.per !== input.per) {
      excluded.otherMeasure += 1;
      continue;
    }
    const priced = offers(card);
    if (priced.length === 0) {
      excluded.noPrice += 1;
      continue;
    }
    if (!sizeHolds(card, priced)) {
      excluded.sizeUnproven += 1;
      continue;
    }
    const amount = multiply(value, parseDecimal(unit.factor));
    for (const { retailer, price, text, currency } of priced) {
      rows.push({
        id: String(card.id),
        brand: card.brand,
        retailer,
        price: text,
        currency,
        size: { value: size.value as string, unit: size.unit },
        perUnit: divide(price, amount, UNIT_PRICE_SCALE),
        per: unit.per,
      });
    }
  }
  const sign = input.order === "asc" ? 1 : -1;
  // Ranked within one measure and one currency: ml before g, then by currency code.
  rows.sort(
    (a, b) =>
      b.per.localeCompare(a.per) ||
      a.currency.localeCompare(b.currency) ||
      sign * compareDecimalText(a.perUnit, b.perUnit) ||
      a.id.localeCompare(b.id) ||
      a.retailer.localeCompare(b.retailer),
  );
  const shown = rows.slice(0, input.rows);
  const matching = typeof total === "number" ? total : null;
  return {
    data: {
      rows: shown,
      total: rows.length,
      truncated: shown.length < rows.length,
      scanned: items.length,
      matching,
      // True when only the first `scanned` of `matching` products (by name) were checked.
      partial: matching !== null && matching > items.length,
      excluded,
    },
  };
}
