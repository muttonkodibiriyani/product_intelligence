import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { EMPTY, type ExploreState } from '@/lib/explore';
import { EmptyResults } from './empty-results';

afterEach(cleanup);

const mount = (
  env: Parameters<typeof EmptyResults>[0]['env'],
  locale: 'en' | 'ar' = 'en',
  state: ExploreState = EMPTY,
) =>
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
      <EmptyResults env={env} state={state} />
    </NextIntlClientProvider>,
  );

const MATCHED: ExploreState = { ...EMPTY, matched: 'yes' };

describe('EmptyResults', () => {
  it('an ok answer with no items: no products match, with the hint', () => {
    mount({ status: 'ok', reason: null });
    expect(screen.getByText(en.explore.empty)).toBeTruthy();
    expect(screen.getByText(en.explore.emptyHint)).toBeTruthy();
  });

  it('data not available: "not available" plus the API reason, never "no products"', () => {
    mount({ status: 'not_enough_data', reason: 'capability_off' });
    expect(screen.getByRole('status').textContent).toContain(en.state.notAvailable);
    expect(screen.getByText(en.reasons.capability_off)).toBeTruthy();
    expect(screen.queryByText(en.explore.empty)).toBeNull();
  });

  it('an unknown reason shows as the API sent it; no reason shows the status alone', () => {
    mount({ status: 'not_enough_data', reason: 'brand_new_reason' as never });
    expect(screen.getByText('brand_new_reason')).toBeTruthy();
    cleanup();
    mount({ status: 'not_enough_data', reason: null });
    expect(screen.getByRole('status').textContent).toBe(en.state.notAvailable);
  });

  it('sold at both shops with nothing listed: no pair published yet, and a way to the category prices', () => {
    mount({ status: 'ok', reason: null }, 'en', MATCHED);
    expect(screen.getByText(en.explore.emptyMatched)).toBeTruthy();
    expect(screen.getByText(en.explore.emptyMatchedHint)).toBeTruthy();
    expect(screen.getByRole('link', { name: en.explore.emptyMatchedLink }).getAttribute('href')).toMatch(
      /\/en\/prices\/?$/,
    );
    expect(screen.queryByText(en.explore.empty)).toBeNull();
    // No shop is named: the pair depends on the data, not on this copy.
    expect(document.body.textContent).not.toMatch(/Ulta|Sephora|Faces/);
  });

  it('sold at both shops plus another filter: the generic message, since that filter may empty the list', () => {
    for (const extra of [
      { brand: ['Clinique'] },
      { category: ['Lipstick'] },
      { q: 'serum' },
      { priceMin: '50' },
      { retailer: ['shop_a'] },
    ] satisfies Partial<ExploreState>[]) {
      mount({ status: 'ok', reason: null }, 'en', { ...MATCHED, ...extra });
      expect(screen.getByText(en.explore.empty)).toBeTruthy();
      expect(screen.getByText(en.explore.emptyHint)).toBeTruthy();
      expect(screen.queryByText(en.explore.emptyMatched)).toBeNull();
      cleanup();
    }
  });

  it('sold at one shop only: the generic message', () => {
    mount({ status: 'ok', reason: null }, 'en', { ...EMPTY, matched: 'no' });
    expect(screen.getByText(en.explore.empty)).toBeTruthy();
    expect(screen.queryByText(en.explore.emptyMatched)).toBeNull();
  });

  it('sold at both shops, data not available: the reason still wins over "no pair"', () => {
    mount({ status: 'not_enough_data', reason: 'capability_off' }, 'en', MATCHED);
    expect(screen.getByText(en.reasons.capability_off)).toBeTruthy();
    expect(screen.queryByText(en.explore.emptyMatched)).toBeNull();
  });

  it('sold at both shops in Arabic', () => {
    mount({ status: 'ok', reason: null }, 'ar', MATCHED);
    expect(screen.getByText(ar.explore.emptyMatched)).toBeTruthy();
    expect(screen.getByRole('link', { name: ar.explore.emptyMatchedLink }).getAttribute('href')).toMatch(
      /\/ar\/prices\/?$/,
    );
  });

  it('in Arabic', () => {
    mount({ status: 'not_enough_data', reason: 'capability_off' }, 'ar');
    expect(screen.getByText(ar.state.notAvailable)).toBeTruthy();
    expect(screen.getByText(ar.reasons.capability_off)).toBeTruthy();
  });
});
