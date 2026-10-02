import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Summary } from '@/lib/api/summary';
import pagesAr from '@/messages/ar.json';
import pages from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgets from '@/messages/widgets.en.json';
import { KpiBand, type RetailerSummary } from './kpis';

const en = { ...pages, widgets };
const ar = { ...pagesAr, widgets: widgetsAr };
const summary = (golden('summary') as { data: Summary }).data;
const pair = {
  base: 'shop_a',
  other: 'shop_b',
  name: (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id,
};
const row = (retailer: string, name: string, data: Summary): RetailerSummary => ({
  retailer,
  name,
  data: { ...data, retailer },
  caveats: [],
});

function band(
  rows: RetailerSummary[],
  locale: 'en' | 'ar' = 'en',
  categories = null as Parameters<typeof KpiBand>[0]['categories'],
) {
  const m = locale === 'ar' ? ar : en;
  render(
    <NextIntlClientProvider locale={locale} messages={m} onError={() => {}}>
      <KpiBand rows={rows} locale={locale} pair={pair} categories={categories} />
    </NextIntlClientProvider>,
  );
  const tile = (label: string) => screen.getByText(label, { exact: true }).closest('div')!;
  return { m, tile };
}

afterEach(cleanup);

describe('KpiBand', () => {
  it('one shop: the median as sent, without a mean, and the count', () => {
    const { m, tile } = band([row('shop_a', 'Shop A', summary)]);
    const median = tile(m.widgets.kpi.median);
    expect(median.textContent).toContain('50.00');
    expect(median.textContent).not.toMatch(/mean/);
    expect(tile(m.widgets.kpi.products).textContent).toContain(String(summary.products));
  });

  it('two shops: hero is the sum, the lead says who lists more, from the two values shown', () => {
    const b = { ...summary, products: (summary.products ?? 0) + 25 };
    const { m, tile } = band([row('shop_a', 'Shop A', summary), row('shop_b', 'Shop B', b)]);
    const products = tile(m.widgets.kpi.products);
    expect(products.textContent).toContain(String((summary.products ?? 0) * 2 + 25));
    expect(products.textContent).toContain('Shop B lists 25 more products');
    expect(within(products).getByText('Shop A')).toBeTruthy();
  });

  it('two shops: the lower median is the hero and the difference is the lead, on minor units', () => {
    const b = { ...summary, medianPrice: { amount: '52.50', currency: 'AED', minor: 5250 } };
    const { m, tile } = band([row('shop_a', 'Shop A', summary), row('shop_b', 'Shop B', b)]);
    const median = tile(m.widgets.kpi.median);
    expect(median.textContent).toMatch(/Shop A is AED\s2\.50 lower/);
    expect(median.textContent).toContain('lowest, at Shop A');
  });

  it('a withheld median reads as not measured, never 0', () => {
    const { m, tile } = band([row('shop_a', 'Shop A', { ...summary, medianPrice: null, meanPrice: null })]);
    const median = tile(m.widgets.kpi.median);
    expect(median.textContent).toContain(m.widgets.kpi.none);
    expect(median.textContent).not.toMatch(/0\.00/);
  });

  it('withheld promotions show the state string with the reason, never 0%', () => {
    const b: Summary = {
      ...summary,
      withheld: [{ section: 'promotions', reason: 'was_price_unverified' }],
      promoSharePct: null,
      promoDepth: null,
      topDiscounts: null,
    };
    const { m, tile } = band([row('shop_a', 'Shop A', summary), row('shop_b', 'Shop B', b)]);
    const promo = tile(m.widgets.kpi.promo);
    expect(promo.textContent).toContain('Shop B discounts: not available yet.');
    expect(promo.textContent).toContain(m.reasons.was_price_unverified);
    expect(promo.textContent).toContain('of Shop A products');
    expect(promo.textContent).not.toMatch(/\b0(\.0)?%/);
  });

  it('the category read replaces the median card once the medians are served', () => {
    const { m, tile } = band([row('shop_a', 'Shop A', summary), row('shop_b', 'Shop B', summary)], 'en', {
      compared: 9,
      base: 2,
      other: 6,
      same: 1,
    });
    const cat = tile(m.widgets.kpi.byCategory);
    expect(cat.textContent).toContain('of 9 categories cheaper at Shop B');
    expect(screen.queryByText(m.widgets.kpi.median, { exact: true })).toBeNull();
  });

  it('in Arabic', () => {
    const { m, tile } = band([row('shop_a', 'Shop A', summary)], 'ar');
    expect(tile(m.widgets.kpi.median).textContent).toContain('50.00');
    expect(tile(m.widgets.kpi.freshness).textContent).toContain('حتى');
  });
});
