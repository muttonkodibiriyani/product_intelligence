'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { formatDate } from '@/lib/format';

export const ULTA_RETAILER = 'ulta_ae';

type Offer = Pick<Schemas['OfferView'], 'retailer' | 'evidence'>;

export type OfferPriceDate =
  { state: 'latest' | 'stale'; date: string } | { state: 'unavailable'; date: null };

/** A real calendar day in the API's date form; rollover dates fail closed. */
function calendarDay(value: unknown): string | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
}

/**
 * The calendar day carried by one offer's API evidence. It is deliberately taken from the
 * timestamp's written date, rather than the browser's timezone or today's clock: imported Ulta
 * snapshots use capturedAt as their per-offer import/as-of evidence.
 */
function evidenceDay(value: unknown): string | null {
  if (
    typeof value !== 'string' ||
    !/^(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  )
    return null;
  const day = value.slice(0, 10);
  return calendarDay(day) && !Number.isNaN(new Date(value).getTime()) ? day : null;
}

/**
 * Ulta's exact offer-level price day, compared only with Ulta's own source day. Missing or bad
 * evidence and impossible future-of-source evidence are unavailable; no state is inferred from
 * the wall clock. When source metadata is unavailable, a valid offer day remains visible but is
 * conservatively stale.
 */
export function offerPriceDate(offer: Offer, sourceDate: string | null): OfferPriceDate | null {
  if (offer.retailer !== ULTA_RETAILER) return null;
  const date = evidenceDay(offer.evidence?.capturedAt);
  const latest = calendarDay(sourceDate);
  if (!date || (latest && date > latest)) return { state: 'unavailable', date: null };
  return { state: latest && date === latest ? 'latest' : 'stale', date };
}

/** The price's own date sits with the price, so a page-wide/latest date cannot overwrite it. */
export function UltaOfferPriceDate({
  offer,
  sourceDate,
  retailerName,
}: {
  offer: Offer;
  sourceDate: string | null;
  retailerName: string;
}) {
  const t = useTranslations('product');
  const locale = useLocale();
  const observed = offerPriceDate(offer, sourceDate);
  if (!observed) return null;
  const stale = observed.state !== 'latest';
  const text = observed.date
    ? t(stale ? 'offerPriceStale' : 'offerPriceAsOf', {
        retailer: retailerName,
        date: formatDate(observed.date, locale),
      })
    : t('offerPriceDateUnavailable', { retailer: retailerName });
  return (
    <span
      data-offer-price-date={ULTA_RETAILER}
      data-price-date-state={observed.state}
      className={`mt-1 block max-w-full break-words text-xs ${stale ? 'font-semibold text-warn' : 'text-ink-2'}`}
    >
      {text}
    </span>
  );
}
