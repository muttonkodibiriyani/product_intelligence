import { useTranslations } from 'next-intl';
import type { Money as MoneyValue } from '@/lib/api/types';
import { formatMoney, isValidMoney, priceState, type AppLocale, type Priced } from '@/lib/money';

/**
 * An API money value, formatted from its exact decimal string. A value that fails the contract's
 * own check is shown as sent (amount and code), never re-rounded into something plausible.
 */
export function Money({ m, locale, signed }: { m: MoneyValue; locale: string; signed?: boolean }) {
  const lc: AppLocale = locale === 'ar' ? 'ar' : 'en';
  const text = isValidMoney(m) ? formatMoney(m, lc) : `${m.amount} ${m.currency}`;
  const plus = signed && !m.amount.startsWith('-') && !/^0*\.?0*$/.test(m.amount) ? '+' : '';
  return <bdi className="tabular-nums whitespace-nowrap">{plus + text}</bdi>;
}

/** A signed percentage string from the API ("25.0", "-4.2"), with its sign kept. */
export function Pct({ v }: { v: string }) {
  const plus = v.startsWith('-') || /^0*\.?0*$/.test(v) ? '' : '+';
  return <bdi className="tabular-nums whitespace-nowrap" dir="ltr">{`${plus}${v}%`}</bdi>;
}

/**
 * An item's price, or "Price under review" when the API flags it (or it is 0.01 or less): the
 * number is never shown. A null price without the flag renders `fallback` (the caller's "no price").
 */
export function Price({
  of,
  locale,
  fallback = null,
}: {
  of: { price?: MoneyValue | null; priceFlag?: Priced['priceFlag'] };
  locale: string;
  fallback?: React.ReactNode;
}) {
  const t = useTranslations('price');
  if (priceState(of) === 'review') return <span className="text-ink-2">{t('underReview')}</span>;
  return of.price ? <Money m={of.price} locale={locale} /> : <>{fallback}</>;
}
