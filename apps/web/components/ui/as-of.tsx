'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import { formatDate } from '@/lib/format';
import { useMeta } from '../use-meta';

/**
 * The page top bar's as-of line: the dataset's cutoff ("Data as of …") from /meta. A page whose
 * numbers hold for other dates (the Overview names each shop's) passes its own wording as
 * `children` in place of the dataset-wide cutoff. The link to "About the data" is in the footer,
 * once, not on every page's top bar. Nothing renders until there is a date.
 */
export function AsOf({ children }: { children?: ReactNode }) {
  const t = useTranslations('app');
  const locale = useLocale();
  const cutoff = useMeta().data?.data?.cutoff;
  const date = children ?? (cutoff && t('asOf', { date: formatDate(cutoff, locale) }));
  if (!date) return null;
  return <p className="text-xs text-ink-2">{date}</p>;
}
