'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';

/**
 * A page's title, the one line saying what it answers, its as-of date with the "About the data"
 * link beside it, and its page-level tools (tabs, a reset). `id` labels the page's section, so the
 * heading names the landmark.
 */
export function PageHeader({
  id,
  title,
  intro,
  asOf,
  tools,
}: {
  id?: string;
  title: ReactNode;
  intro?: ReactNode;
  /** The date the page's data is as of, already worded; the About link follows it. */
  asOf?: ReactNode;
  tools?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1">
        <h1 id={id} className="text-2xl font-bold tracking-tight">
          {title}
        </h1>
        {intro && <div className="mt-1 max-w-prose text-sm text-ink-2">{intro}</div>}
        <p className="mt-1 text-xs text-ink-2">
          {asOf && <>{asOf} · </>}
          <AboutDataLink />
        </p>
      </div>
      {tools}
    </div>
  );
}

/** The one link to the plain-words "About the data" section on the Dataset page. */
export function AboutDataLink({ className = '' }: { className?: string }) {
  const t = useTranslations('app');
  const locale = useLocale();
  return (
    <Link
      href={`/${locale}/dataset/#about-data`}
      className={`text-accent underline-offset-2 hover:underline focus-visible:outline-2 ${className}`}
    >
      {t('aboutData')}
    </Link>
  );
}
