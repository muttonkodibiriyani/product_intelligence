'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';

/**
 * The mark: a rounded tile with two price bars cut out of it, side by side on one baseline, one
 * shorter than the other: two shops' prices head to head, which is what the product does. One
 * path in one colour (the bars are holes, by even-odd fill), so it takes the text colour wherever
 * it sits and reads the same in RTL; drawn on a 16-unit grid so it stays crisp at 16 and 32px.
 * The same path is the favicon (app/icon.svg).
 */
export const MARK_PATH =
  'M4 0h8a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4H4a4 4 0 0 1-4-4V4a4 4 0 0 1 4-4Zm0 8v5h3V8H4Zm5-4v9h3V4H9Z';

export function LogoMark({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 16 16"
      className={`shrink-0 ${className}`}
      focusable="false"
    >
      <path d={MARK_PATH} fill="currentColor" fillRule="evenodd" />
    </svg>
  );
}

/**
 * The logo: the mark and the wordmark (the app's name in its own type, with the tagline under it
 * unless compact), as the link home. The link's accessible name is the app's name; the mark is
 * decorative. In Arabic the mark keeps its shape and the wordmark sits at its other side.
 */
export function Logo({ compact = false, className = '' }: { compact?: boolean; className?: string }) {
  const t = useTranslations('app');
  const locale = useLocale();
  return (
    <Link
      href={`/${locale}/`}
      aria-label={t('name')}
      className={`flex items-center gap-2.5 rounded-ctl whitespace-nowrap text-ink focus-visible:outline-2 ${className}`}
    >
      <LogoMark />
      <span className="leading-tight">
        <b className="block text-[14px] font-bold tracking-tight">{t('name')}</b>
        {!compact && <span className="block text-[11px] text-ink-2">{t('tagline')}</span>}
      </span>
    </Link>
  );
}
