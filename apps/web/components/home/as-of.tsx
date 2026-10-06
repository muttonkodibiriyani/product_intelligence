'use client';

import { useLocale, useTranslations } from 'next-intl';
import { formatDate } from '@/lib/format';
import type { RetailerSummary } from '../widgets/kpis';
import { freshness, importedOn } from '../widgets/model';

/** The date an imported retailer's snapshot was taken, or null for a collected one. */
function importedDate(r: RetailerSummary): string | null {
  const on = importedOn(r.caveats, r.retailer);
  return freshness(r.data.freshness) === 'snapshot' || on ? (on ?? r.data.freshness.cutoff) : null;
}

/**
 * The line under the landing's title saying which date the numbers hold for. Collected retailers
 * that share one as-of date are said once, without names; when their dates differ (one source is
 * stale) each shop is named with its own date, so no date can be read as another shop's. An
 * imported retailer always reads as a one-off snapshot with its import date.
 */
export function AsOf({ rows }: { rows: readonly RetailerSummary[] }) {
  const t = useTranslations('state');
  const locale = useLocale();
  if (rows.length === 0) return null;
  const collected = rows.filter((r) => importedDate(r) === null);
  const dates = new Set(collected.map((r) => r.data.asOf));
  const parts =
    dates.size === 1
      ? [t('asOf', { date: formatDate(collected[0]!.data.asOf, locale) })]
      : collected.map((r) => t('asOfRetailer', { retailer: r.name, date: formatDate(r.data.asOf, locale) }));
  for (const r of rows) {
    const on = importedDate(r);
    if (on) parts.push(t('snapshotOneOff', { retailer: r.name, date: formatDate(on, locale) }));
  }
  return <>{parts.join(' · ')}</>;
}
