'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { navHref } from '@/lib/nav';

/** Summary and Every match: the same pair and filters, two ways to read them. */
export function CompareViews({ current, search }: { current: 'summary' | 'overlap'; search: string }) {
  const t = useTranslations('overlap');
  const locale = useLocale();
  const base = navHref('compare', locale);
  const tab = (key: 'summary' | 'overlap', href: string, label: string) => (
    <Link
      href={href}
      aria-current={current === key ? 'page' : undefined}
      className={`border-b-2 px-0.5 pb-1.5 text-sm focus-visible:outline-2 ${
        current === key
          ? 'border-accent font-semibold text-ink'
          : 'border-transparent text-ink-2 hover:text-ink'
      }`}
    >
      {label}
    </Link>
  );
  return (
    <nav aria-label={t('views')} className="flex gap-5">
      {tab('summary', `${base}${search}`, t('toSummary'))}
      {tab('overlap', `${base}overlap/${search}`, t('toOverlap'))}
    </nav>
  );
}
