'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { LANG_KEY, type Locale } from '@/i18n/routing';

/** Same page in the other language: swaps the first path segment. */
export function otherLocalePath(pathname: string, to: Locale): string {
  const rest = pathname.replace(/^\/(en|ar)(?=\/|$)/, '');
  return `/${to}${rest || '/'}`;
}

export function LangSwitch() {
  const t = useTranslations('app');
  const locale = useLocale();
  const to: Locale = locale === 'ar' ? 'en' : 'ar';
  return (
    <Link
      href={otherLocalePath(usePathname(), to)}
      hrefLang={to}
      lang={to}
      aria-label={t('switchLangLabel')}
      onClick={() => localStorage.setItem(LANG_KEY, to)}
      className="rounded px-2 py-1 text-sm text-ink-2 hover:bg-surface-2 focus-visible:outline-2"
    >
      {t('switchLang')}
    </Link>
  );
}
