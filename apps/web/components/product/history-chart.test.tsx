import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Schemas } from '@/lib/api/types';
import en from '@/messages/en.json';
import { HistoryChart } from './history-chart';

type Series = Schemas['History']['series'];
const series = (golden('history') as { data: { series: Series } }).data.series;
const firstDay = Object.fromEntries(
  Object.entries(series).map(([r, pts]) => [r, (pts ?? []).slice(0, 1)]),
) as Series;

function show(s: Series) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} onError={() => {}}>
      <HistoryChart series={s} name={(id) => id} />
    </NextIntlClientProvider>,
  );
}

afterEach(cleanup);

describe('HistoryChart', () => {
  it('draws a line once there are two or more days', () => {
    const { container } = show(series);
    expect(container.querySelector('polyline')).not.toBeNull();
    expect(screen.queryByText(en.product.historyBegins)).toBeNull();
  });

  it('draws no line from a single day: says why and shows that day as a table', () => {
    const { container } = show(firstDay);
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    expect(screen.getByText(en.product.historyBegins)).toBeTruthy();
    expect(screen.getByRole('table')).toBeTruthy();
    expect(screen.getByText('AED 120.00')).toBeTruthy();
  });

  it('a day priced 0.01 or less is neither plotted nor an axis label; the table says "Price under review"', () => {
    const low = structuredClone(series);
    low.shop_a![1]!.price = { amount: '0.01', currency: 'AED', minor: 1 };
    show(low);
    expect(screen.queryByText(/AED\s*0\.01/)).toBeNull();
    expect(screen.getByText(en.price.underReview)).toBeTruthy();
  });

  it('a single day priced 0.01 or less: the table says "Price under review", never the number', () => {
    const low = structuredClone(firstDay);
    low.shop_a![0]!.price = { amount: '0.00', currency: 'AED', minor: 0 };
    show(low);
    expect(screen.queryByText(/AED\s*0\.00/)).toBeNull();
    expect(screen.getByText(en.price.underReview)).toBeTruthy();
  });
});
