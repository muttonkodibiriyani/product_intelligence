'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
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
  const router = useRouter();
  const to: Locale = locale === 'ar' ? 'en' : 'ar';
  const href = otherLocalePath(usePathname(), to);
  return (
    <Link
      href={href}
      hrefLang={to}
      lang={to}
      aria-label={t('switchLangLabel')}
      onClick={(e) => {
        localStorage.setItem(LANG_KEY, to);
        // Keep the query (filters, product id): the static page can only read it in the browser.
        if (window.location.search && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
          e.preventDefault();
          router.push(href + window.location.search);
        }
      }}
      className="rounded px-2 py-1 text-sm text-ink-2 hover:bg-surface-2 focus-visible:outline-2"
    >
      {t('switchLang')}
    </Link>
  );
}
