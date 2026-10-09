'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Schemas } from '@/lib/api/types';
import { formatDate } from '@/lib/format';
import { retailerName } from '@/lib/retailers';
import { useMeta } from '../use-meta';

const ULTA = 'ulta_ae';

/**
 * One retailer's unambiguous observation day from /meta. Exact ids keep one shop's date from
 * leaking onto another; missing, malformed, or conflicting source metadata fails closed.
 */
export function sourceObservationDate(
  meta: Schemas['MetaView'] | null | undefined,
  retailer: string,
): string | null {
  const observed = sourceObservation(meta, retailer);
  return observed.state === 'ok' ? observed.date : null;
}

/** Why a retailer's observation day is or is not usable: absent, unreadable, or conflicting. */
export type SourceObservation =
  { state: 'ok'; date: string } | { state: 'unavailable' | 'invalid' | 'conflict'; date: null };

export function sourceObservation(
  meta: Schemas['MetaView'] | null | undefined,
  retailer: string,
): SourceObservation {
  const sources = meta?.sources.filter((source) => source.source === retailer) ?? [];
  if (sources.length === 0) return { state: 'unavailable', date: null };
  if (sources.length > 1) return { state: 'conflict', date: null };
  const date = sources[0]!.lastDate;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return { state: 'invalid', date: null };
  const parsed = new Date(`${date}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date
    ? { state: 'ok', date }
    : { state: 'invalid', date: null };
}

const DATE_KEY = {
  unavailable: 'retailerPriceDateUnknown',
  invalid: 'retailerPriceDateInvalid',
  conflict: 'retailerPriceDateConflict',
} as const;

/** Ulta's latest source day as context; individual offer labels remain authoritative. */
export function UltaPriceDate({ meta }: { meta: Schemas['MetaView'] | null | undefined }) {
  const t = useTranslations('app');
  const locale = useLocale();
  const ulta = meta?.retailers.find((retailer) => retailer.id === ULTA);
  if (!ulta) return null;
  const observed = sourceObservation(meta, ULTA);
  const name = retailerName(ULTA, ulta.name, locale);
  return (
    <span data-retailer-date={ULTA} data-date-state={observed.state} className="break-words">
      {observed.state === 'ok'
        ? t('retailerLatestPriceData', { retailer: name, date: formatDate(observed.date, locale) })
        : t(DATE_KEY[observed.state], { retailer: name })}
    </span>
  );
}

/**
 * The page top bar's as-of line: the dataset's cutoff ("Data as of …") from /meta. A page whose
 * numbers hold for other dates (the Overview names each shop's) passes its own wording as
 * `children` in place of the dataset-wide cutoff. The link to "About the data" is in the footer,
 * once, not on every page's top bar. Nothing renders until there is a date.
 */
export function AsOf({ children }: { children?: ReactNode }) {
  const t = useTranslations('app');
  const locale = useLocale();
  const meta = useMeta().data?.data;
  const cutoff = meta?.cutoff;
  const date = children ?? (cutoff && t('asOf', { date: formatDate(cutoff, locale) }));
  const hasUlta = meta?.retailers.some((retailer) => retailer.id === ULTA);
  if (!date && !hasUlta) return null;
  return (
    <p className="max-w-full text-xs text-ink-2">
      {date}
      {date && hasUlta && <span aria-hidden> · </span>}
      <UltaPriceDate meta={meta} />
    </p>
  );
}
