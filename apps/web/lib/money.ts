import type { Money } from './api/types';

/** ISO 4217 minor-unit exponent, from the platform's currency data (AED 2, KWD 3, JPY 0). */
export function currencyExponent(currency: string): number {
  return (
    new Intl.NumberFormat('en', { style: 'currency', currency }).resolvedOptions().maximumFractionDigits ?? 2
  );
}

/**
 * True when `amount` has exactly the currency's decimals and `minor` is the same value in minor
 * units. Checked on strings, so no floating point is involved.
 */
export function isValidMoney(m: Money): boolean {
  const exp = currencyExponent(m.currency);
  const re = exp === 0 ? /^-?\d+$/ : new RegExp(`^-?\\d+\\.\\d{${exp}}$`);
  if (!re.test(m.amount)) return false;
  const digits = m.amount.replace('.', '').replace(/^(-?)0+(?=\d)/, '$1');
  return digits === String(m.minor) || (digits === '-0' && m.minor === 0);
}

/**
 * Owner rule: a price of 0.01 or less is a placeholder, not a price. The API is adding
 * `priceFlag: "invalid_low"` (with `price: null`) for those; until it ships, the amount itself is
 * the guard. This is the one place that decides, so every table, chart and sort agrees.
 */
export function isValidAmount(amount: string): boolean {
  if (!/^-?\d+(\.\d+)?$/.test(amount)) return false;
  const v = Number(amount);
  return Number.isFinite(v) && v > 0.01;
}

/** Anything with a price: an offer, a pair row's side, a top discount. `priceFlag` is read defensively. */
export type Priced = { price?: (Pick<Money, 'amount'> & Partial<Money>) | null };

/**
 * `review`: the price is withheld as invalid, shown as "Price under review" and left out of every
 * client-side sort, join and chart. `ok` otherwise, including a null price without the flag, which
 * keeps its existing "no price" handling.
 */
export function priceState(x: Priced | null | undefined): 'ok' | 'review' {
  if (!x) return 'ok';
  if ((x as { priceFlag?: unknown }).priceFlag === 'invalid_low') return 'review';
  return x.price && !isValidAmount(x.price.amount) ? 'review' : 'ok';
}

/** A present, real price: what item-level math may use. */
export const isValidPrice = (m: (Pick<Money, 'amount'> & Partial<Money>) | null | undefined): m is Money =>
  !!m && priceState({ price: m }) === 'ok';

export type AppLocale = 'en' | 'ar';

/**
 * Formats the exact decimal string (Intl accepts strings, so 1234.50 never passes through a
 * float). Latin digits in both languages, so numbers line up in tables and match the evidence.
 */
export function formatMoney(m: Money, locale: AppLocale): string {
  const fmt = new Intl.NumberFormat(locale === 'ar' ? 'ar-AE' : 'en-AE', {
    style: 'currency',
    currency: m.currency,
    numberingSystem: 'latn',
  });
  return fmt.format(m.amount as Intl.StringNumericLiteral);
}
