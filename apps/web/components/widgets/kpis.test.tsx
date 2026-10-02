import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Schemas } from '@/lib/api/types';
import pages from '@/messages/en.json';
import widgets from '@/messages/widgets.en.json';
import { KpiWidget, PairKpis, type RetailerSummary } from './kpis';
import type { Summary } from '@/lib/api/summary';

const en = { ...pages, widgets };
const compare = (golden('compare') as { data: Schemas['Comparison'] }).data;
const pair = {
  base: 'shop_a',
  other: 'shop_b',
  name: (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id,
};

function show(data: Schemas['Comparison']) {
  render(
    <NextIntlClientProvider locale="en" messages={en} onError={() => {}}>
      <PairKpis data={data} pair={pair} locale="en" href="/compare" />
    </NextIntlClientProvider>,
  );
  const tile = screen.getByText(en.widgets.kpi.cheaper).closest('div')!;
  const row = (name: string) => within(tile).getByText(name).closest('dd')!;
  return { row };
}

afterEach(cleanup);

const summary = (golden('summary') as { data: Summary }).data;
const retailer = (id: string, name: string, over: Partial<Summary> = {}): RetailerSummary => ({
  retailer: id,
  name,
  data: { ...structuredClone(summary), retailer: id, ...over },
  caveats: [],
});

function showKpis(rows: RetailerSummary[]) {
  const { container } = render(
    <NextIntlClientProvider locale="en" messages={en} onError={() => {}}>
      <KpiWidget rows={rows} locale="en" />
    </NextIntlClientProvider>,
  );
  return container;
}

describe('KpiWidget: promotion share', () => {
  const withheld: Summary['withheld'] = [{ section: 'promotions', reason: 'capability_off' }];

  it('a withheld share reads as not available, never as 0%', () => {
    const container = showKpis([
      retailer('shop_a', 'Shop A'),
      retailer('shop_b', 'Shop B', { withheld, promoSharePct: null, promoDepth: null, topDiscounts: null }),
    ]);
    const tile = screen.getByText(en.widgets.kpi.promo).closest('div')!;
    const b = within(tile).getByText('Shop B').closest('dd')!;
    expect(b.textContent).toContain('Not available yet');
    expect(b.textContent).not.toMatch(/%|\d/);
    expect(within(tile).getByText('Shop A').closest('dd')!.textContent).toContain('50%');
    // A 0% anywhere would be a withheld share shown as zero (50% is Shop A's real share).
    expect(container.textContent).not.toMatch(/(^|[^\d.])0%/);
  });

  it('with every share withheld the tile is left out, so nothing on it can read as 0%', () => {
    const container = showKpis([
      retailer('shop_a', 'Shop A', { withheld, promoSharePct: null, promoDepth: null, topDiscounts: null }),
    ]);
    expect(screen.queryByText(en.widgets.kpi.promo)).toBeNull();
    expect(container.textContent).not.toMatch(/\d%/);
  });
});

describe('PairKpis: cheaper at', () => {
  it('shows each retailer’s wins as sent', () => {
    const { row } = show(compare);
    expect(row('Shop A').textContent).toContain('3');
    expect(row('Shop B').textContent).toContain('2');
  });

  it('a retailer missing from cheaperCounts reads as a dash, never 0', () => {
    const data = structuredClone(compare);
    data.summary!.cheaperCounts = { shop_a: 3 };
    const { row } = show(data);
    expect(row('Shop A').textContent).toContain('3');
    expect(row('Shop B').textContent).toContain('–');
    expect(row('Shop B').textContent).not.toMatch(/\d/);
  });
});
