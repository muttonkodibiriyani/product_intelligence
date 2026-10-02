'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { formatDate } from '@/lib/format';
import { datasetHref } from '@/lib/nav';
import { useMeta } from '../use-meta';

/**
 * The dataset's cutoff ("Data as of …") from /meta, and the link to the Dataset section. The date
 * waits for /meta; the link is always there.
 */
export function AsOf() {
  const t = useTranslations('app');
  const locale = useLocale();
  const cutoff = useMeta().data?.data?.cutoff;
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 text-xs text-ink-2">
      {cutoff && (
        <>
          <span>{t('asOf', { date: formatDate(cutoff, locale) })}</span>
          <span aria-hidden="true">·</span>
        </>
      )}
      <Link
        href={datasetHref(locale)}
        className="rounded-sm underline underline-offset-2 hover:text-ink focus-visible:outline-2"
      >
        {t('aboutData')}
      </Link>
    </div>
  );
}
