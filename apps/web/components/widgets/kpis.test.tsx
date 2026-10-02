import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Schemas } from '@/lib/api/types';
import pages from '@/messages/en.json';
import widgets from '@/messages/widgets.en.json';
import { PairKpis } from './kpis';

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
