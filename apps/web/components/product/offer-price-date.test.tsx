import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { offerPriceDate, UltaOfferPriceDate } from './offer-price-date';

type Offer = Schemas['OfferView'];

const offer = (retailer: string, capturedAt: unknown): Offer =>
  ({ retailer, evidence: { capturedAt, url: null } }) as Offer;

function label(o: Offer, sourceDate: string | null, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en}>
      <UltaOfferPriceDate offer={o} sourceDate={sourceDate} retailerName="Ulta Beauty UAE" />
    </NextIntlClientProvider>,
  ).container;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('offerPriceDate', () => {
  it('keeps a retained Oct-1 offer stale beside the Oct-9 source and keeps an Oct-9 candidate Oct-9', () => {
    expect(offerPriceDate(offer('ulta_ae', '2026-10-01T07:15:12Z'), '2026-10-09')).toEqual({
      state: 'stale',
      date: '2026-10-01',
    });
    expect(offerPriceDate(offer('ulta_ae', '2026-10-09T11:25:00+04:00'), '2026-10-09')).toEqual({
      state: 'latest',
      date: '2026-10-09',
    });
  });

  it('fails closed for missing, malformed, rollover, and source-conflicting offer evidence', () => {
    for (const capturedAt of [undefined, '', 'soon', '2026-02-30T00:00:00Z']) {
      expect(offerPriceDate(offer('ulta_ae', capturedAt), '2026-10-09')).toEqual({
        state: 'unavailable',
        date: null,
      });
    }
    expect(offerPriceDate(offer('ulta_ae', '2026-10-10T00:00:00Z'), '2026-10-09')).toEqual({
      state: 'unavailable',
      date: null,
    });
  });

  it('does not infer freshness from the wall clock and treats an unknown source day as stale', () => {
    vi.useFakeTimers();
    vi.setSystemTime('2020-01-01T00:00:00Z');
    const first = offerPriceDate(offer('ulta_ae', '2026-10-01T07:15:12Z'), null);
    vi.setSystemTime('2040-01-01T00:00:00Z');
    expect(offerPriceDate(offer('ulta_ae', '2026-10-01T07:15:12Z'), null)).toEqual(first);
    expect(first).toEqual({ state: 'stale', date: '2026-10-01' });
  });

  it('is retailer-isolated', () => {
    expect(offerPriceDate(offer('sephora_me', '2026-10-01T07:15:12Z'), '2026-10-09')).toBeNull();
    expect(label(offer('sephora_me', '2026-10-01T07:15:12Z'), '2026-10-09').textContent).toBe('');
  });
});

describe('UltaOfferPriceDate', () => {
  it('visibly and wrap-safely labels the retained offer as stale in English and Arabic', () => {
    const o = offer('ulta_ae', '2026-10-01T07:15:12Z');
    const node = label(o, '2026-10-09').querySelector('[data-offer-price-date="ulta_ae"]');
    expect(node?.textContent).toBe('Stale: Ulta Beauty UAE price data as of 1 Oct 2026');
    expect(node?.className).toContain('break-words');
    expect(node?.getAttribute('data-price-date-state')).toBe('stale');
    expect(label(o, '2026-10-09', 'ar').textContent).toMatch(/قديم.*Ulta.*1.*10.*2026/);
  });

  it('labels an Oct-9 candidate with its own date and marks bad evidence stale', () => {
    expect(label(offer('ulta_ae', '2026-10-09T07:25:00Z'), '2026-10-09').textContent).toBe(
      'Ulta Beauty UAE price data as of 9 Oct 2026',
    );
    expect(label(offer('ulta_ae', 'bad'), '2026-10-09').textContent).toBe(
      'Stale: Ulta Beauty UAE price date unavailable',
    );
  });
});
