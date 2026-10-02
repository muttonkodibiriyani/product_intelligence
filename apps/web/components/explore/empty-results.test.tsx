import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { EmptyResults } from './empty-results';

afterEach(cleanup);

const mount = (env: Parameters<typeof EmptyResults>[0]['env'], locale: 'en' | 'ar' = 'en') =>
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      <EmptyResults env={env} />
    </NextIntlClientProvider>,
  );

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

  it('in Arabic', () => {
    mount({ status: 'not_enough_data', reason: 'capability_off' }, 'ar');
    expect(screen.getByText(ar.state.notAvailable)).toBeTruthy();
    expect(screen.getByText(ar.reasons.capability_off)).toBeTruthy();
  });
});
