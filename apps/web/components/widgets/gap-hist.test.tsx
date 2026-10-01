import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgets from '@/messages/widgets.en.json';
import type { Palette } from './chart';
import { GapHistWidget } from './charts';
import { gapBinSign, gapHistBins } from './model';

// The chart is ECharts; here it hands back the option the widget builds, on a palette of names.
type Built = {
  yAxis: { data: string[] };
  series: { data: { value: number; itemStyle: { color: string } }[] }[];
};
const built: { label: string; option: Built }[] = [];
vi.mock('./chart', async (orig) => ({
  ...(await orig<typeof import('./chart')>()),
  Chart: ({ label, build }: { label: string; build: (p: Palette) => unknown }) => {
    const p = new Proxy({}, { get: (_, k) => String(k) }) as Palette;
    built.push({ label, option: build(p) as Built });
    return null;
  },
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const cmp = (golden('compare') as { data: Schemas['Comparison'] }).data;
const hist = cmp.summary!.gapHist;
const pair = { base: 'shop_a', other: 'shop_b', name: (id: string) => id };

function draw(data: Schemas['GapHistogram'], locale: 'en' | 'ar' = 'en') {
  built.length = 0;
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? { ...ar, widgets: widgetsAr } : { ...en, widgets }}
      onError={() => {}}
    >
      <GapHistWidget data={data} currency="AED" locale={locale} pair={pair} />
    </NextIntlClientProvider>,
  );
  expect(built).toHaveLength(1);
  return built[0]!;
}

afterEach(cleanup);

describe('gapHistBins', () => {
  it('reads the 11 bins as sent, open at both tails, summing to the pairs counted', () => {
    const bins = gapHistBins(hist);
    expect(bins).toHaveLength(11);
    expect(bins[0]).toEqual({ lo: null, hi: '-50', count: hist.counts[0] });
    expect(bins[5]).toMatchObject({ lo: '-1', hi: '1' }); // 0 lands here: the near-parity bin
    expect(bins[10]).toEqual({ lo: '50', hi: null, count: hist.counts[10] });
    expect(bins.reduce((s, b) => s + b.count, 0)).toBe(cmp.summary!.n);
  });

  it('draws nothing when the counts do not fit the edges', () => {
    expect(gapHistBins({ edges: hist.edges, counts: hist.counts.slice(1) })).toEqual([]);
    expect(gapHistBins({ edges: [], counts: [3] })).toEqual([]);
    expect(gapHistBins(null)).toEqual([]);
  });

  it('leans each bin to a side: below zero the other retailer is cheaper, [-1, 1) is neither', () => {
    expect(gapHistBins(hist).map(gapBinSign)).toEqual([-1, -1, -1, -1, -1, 0, 1, 1, 1, 1, 1]);
  });
});

describe('GapHistWidget', () => {
  it('names each bar by its range, with "< −50%" and "≥ +50%" at the tails', () => {
    const { label, option } = draw(hist);
    expect(label).toBe('Matched pairs per price-gap band, 11 bands.');
    expect(option.yAxis.data).toEqual([
      '< −50%',
      '−50% to −25%',
      '−25% to −10%',
      '−10% to −5%',
      '−5% to −1%',
      '−1% to +1%',
      '+1% to +5%',
      '+5% to +10%',
      '+10% to +25%',
      '+25% to +50%',
      '≥ +50%',
    ]);
    expect(option.yAxis.data[0]).not.toContain('≤');
  });

  it('draws one bar per bin with the served count, tinted by side', () => {
    const { option } = draw(hist);
    const bars = option.series[0]!.data;
    expect(bars.map((b) => b.value)).toEqual(hist.counts);
    expect(bars.map((b) => b.itemStyle.color)).toEqual([
      ...Array<string>(5).fill('b'),
      'line3',
      ...Array<string>(5).fill('a'),
    ]);
  });

  it('in Arabic, with no bidi marks in the axis labels', () => {
    const { option } = draw(hist, 'ar');
    expect(option.yAxis.data[0]).toBe('< −50%');
    expect(option.yAxis.data[1]).toBe('−50% إلى −25%');
    expect(option.yAxis.data.join('')).not.toMatch(/[‎‏]/);
  });
});
