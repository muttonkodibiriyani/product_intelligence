import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Summary } from '@/lib/api/summary';
import pagesAr from '@/messages/ar.json';
import pages from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgets from '@/messages/widgets.en.json';
import { KpiWidget } from './kpis';

const en = { ...pages, widgets };
const ar = { ...pagesAr, widgets: widgetsAr };
const summary = (golden('summary') as { data: Summary }).data;

function medianTile(data: Summary, locale: 'en' | 'ar' = 'en') {
  const m = locale === 'ar' ? ar : en;
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={m}
      onError={(e) => {
        throw e;
      }}
    >
      <KpiWidget rows={[{ retailer: 'shop_a', name: 'Shop A', data, caveats: [] }]} locale={locale} />
    </NextIntlClientProvider>,
  );
  return screen.getByText(m.widgets.kpi.median).closest('div')!;
}

afterEach(cleanup);

describe('KpiWidget: mean price', () => {
  it('shows the served mean under the median, as sent', () => {
    expect(summary.meanPrice?.amount).toBe('71.48');
    const tile = medianTile(summary);
    expect(tile.textContent).toContain('50.00');
    expect(tile.textContent).toMatch(/mean AED\s71\.48/);
  });

  it('a null mean is left out, never shown as 0', () => {
    const tile = medianTile({ ...summary, meanPrice: null });
    expect(tile.textContent).toContain('50.00');
    expect(tile.textContent).not.toMatch(/mean/);
    expect(tile.textContent).not.toMatch(/AED\s0\.00/);
  });

  it('in Arabic', () => {
    const tile = medianTile(summary, 'ar');
    expect(tile.textContent).toContain('المتوسط');
    expect(tile.textContent).toContain('71.48');
  });
});
