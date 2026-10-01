import type { Localized } from './api/types';

export type Locale = 'en' | 'ar';

/** Localised text with English as the fallback when a translation is missing. */
export function loc(l: Partial<Localized> | null | undefined, locale: string): string {
  return (locale === 'ar' ? l?.ar : undefined) ?? l?.en ?? '';
}

/**
 * A date (or timestamp) in the user's language, Latin digits, read as UTC. Anything that isn't a
 * valid date is returned exactly as sent, so one bad value never takes the page down.
 */
export function formatDate(iso: string, locale: string, withTime = false): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-AE' : 'en-GB', {
    dateStyle: 'medium',
    ...(withTime ? { timeStyle: 'short' } : {}),
    timeZone: 'UTC',
    numberingSystem: 'latn',
  }).format(d);
}
