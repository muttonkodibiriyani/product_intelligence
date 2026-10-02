import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Summary } from '@/lib/api/summary';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import type { RetailerSummary } from '../widgets/kpis';
import { AsOf } from './as-of';

const base = (golden('summary') as { data: Summary }).data;
const row = (retailer: string, name: string, asOf: string, over: Partial<Summary> = {}): RetailerSummary => ({
  retailer,
  name,
  data: { ...structuredClone(base), retailer, asOf, ...over },
  caveats: [],
});

function text(rows: RetailerSummary[], locale: 'en' | 'ar' = 'en') {
  const { container } = render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      <AsOf rows={rows} />
    </NextIntlClientProvider>,
  );
  return container.textContent;
}

afterEach(cleanup);

describe('AsOf', () => {
  it('says one date, with no shop names, when the collected shops share it', () => {
    const s = text([row('shop_a', 'Shop A', '2026-10-01'), row('shop_b', 'Shop B', '2026-10-01')]);
    expect(s).toBe('Data as of 1 Oct 2026');
  });

  it('names each shop with its own date when the dates differ, so a stale source is not hidden', () => {
    const s = text([row('shop_a', 'Shop A', '2026-10-01'), row('shop_b', 'Shop B', '2026-09-20')]);
    expect(s).toBe('Shop A: data as of 1 Oct 2026 · Shop B: data as of 20 Sept 2026');
    expect(
      text([row('shop_a', 'Shop A', '2026-10-01'), row('shop_b', 'Shop B', '2026-09-20')], 'ar'),
    ).toMatch(/^Shop A: البيانات حتى .+ · Shop B: البيانات حتى .+$/);
  });

  it('reads an imported shop as a one-off snapshot with its import date, after the collected ones', () => {
    const imported = row('ulta_ae', 'Ulta', '2026-09-28', {
      freshness: { status: 'snapshot', cutoff: '2026-09-28T00:00:00Z', ageDays: 4 },
    });
    const s = text([row('shop_a', 'Shop A', '2026-10-01'), imported]);
    expect(s).toBe('Data as of 1 Oct 2026 · Ulta: one-off snapshot imported 28 Sept 2026');
  });
});
