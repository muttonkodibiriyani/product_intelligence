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
