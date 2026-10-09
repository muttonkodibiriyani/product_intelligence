'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useMemo } from 'react';
import { shopNotices } from '@/lib/dated-shops';
import { formatDate, loc } from '@/lib/format';
import { useCoverage, useMeta, useRetailerName } from '../use-meta';
import { activeRetailers } from '../widgets/model';

/**
 * One line per shown shop whose prices stop before the data's cutoff day, with its last collected
 * date and the reason the data gives; and one per pilot shop this data does not hold. Nothing at
 * all when every shown shop is current, or before /meta and /coverage have loaded.
 */
export function DatedShopNotice({ shops, className = '' }: { shops: readonly string[]; className?: string }) {
  const t = useTranslations('shopNotice');
  const locale = useLocale();
  const name = useRetailerName();
  const meta = useMeta().data?.data;
  const coverage = useCoverage().data?.data?.retailers;
  const notices = useMemo(
    () => shopNotices(meta, coverage, shops, activeRetailers(meta)),
    [meta, coverage, shops],
  );
  if (notices.length === 0) return null;
  return (
    <div
      role="note"
      data-testid="dated-shop-notice"
      className={`space-y-1 panel px-4 py-3 text-sm ${className}`}
    >
      {notices.map((n) => {
        if (n.kind === 'absent')
          return (
            <p key={`absent:${n.id}`} className="text-ink-2">
              {t('absent', { shop: name(n.id) })}
            </p>
          );
        const note = loc(n.note, locale);
        const args = { shop: name(n.id), date: formatDate(n.date, locale) };
        return <p key={`asOf:${n.id}`}>{note ? t('asOfNote', { ...args, note }) : t('asOf', args)}</p>;
      })}
    </div>
  );
}
