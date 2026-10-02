export const locales = ['en', 'ar'] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = 'en';

export function isLocale(v: unknown): v is Locale {
  return typeof v === 'string' && (locales as readonly string[]).includes(v);
}

export const dirOf = (l: Locale) => (l === 'ar' ? 'rtl' : 'ltr');

/** Last language the user picked, read by the root page to choose /en/ or /ar/. */
export const LANG_KEY = 'pi.lang';
