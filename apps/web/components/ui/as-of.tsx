'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import { formatDate } from '@/lib/format';
import { aboutDataHref } from '@/lib/nav';
import { useMeta } from '../use-meta';

/**
 * The page top bar's as-of line: the dataset's cutoff ("Data as of …") from /meta, then the one
 * link to "About the data". A page whose numbers hold for other dates (the Overview names each
 * shop's) passes its own wording as `children` in place of the dataset-wide cutoff. The date waits
 * for /meta; the link is always there.
 */
export function AsOf({ children }: { children?: ReactNode }) {
  const t = useTranslations('app');
  const locale = useLocale();
  const cutoff = useMeta().data?.data?.cutoff;
  const date = children ?? (cutoff && t('asOf', { date: formatDate(cutoff, locale) }));
  return (
    <p className="text-xs text-ink-2">
      {date && <>{date} · </>}
      <Link
        href={aboutDataHref(locale)}
        className="rounded-sm underline underline-offset-2 hover:text-ink focus-visible:outline-2"
      >
        {t('aboutData')}
      </Link>
    </p>
  );
}
