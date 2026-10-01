import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Summary } from '@/lib/api/summary';
import en from '@/messages/en.json';
import type { Schemas } from '@/lib/api/types';
import { productHref } from '../explore/product-table';
import {
  BrandPriceWidget,
  BrandShareWidget,
  CategoryMixWidget,
  CheaperHeatmapWidget,
  CheaperShareWidget,
  CrossHeatmapWidget,
  GroupGapWidget,
  LadderWidget,
  PriceHistWidget,
  PromoDepthWidget,
  TopGapsWidget,
} from './charts';
import {
  bandFloor,
  categoryNodeHref,
  categoryNodes,
  compareHref,
  crossCells,
  exploreHref,
  histBins,
  promotionsHref,
} from './model';

// The chart itself is ECharts; here it only hands back the mark handler each widget gives it.
const picks: ((name: string, data: unknown) => void)[] = [];
vi.mock('./chart', async (orig) => ({
  ...(await orig<typeof import('./chart')>()),
  Chart: ({ onPick }: { onPick?: (name: string, data: unknown) => void }) => {
    if (onPick) picks.push(onPick);
    return null;
  },
}));
const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const s = (golden('summary') as { data: Summary }).data;
const locale = 'en';
const common = { currency: s.currency, locale };

/** Renders a widget, clicks its one mark, and returns where the drill went. */
function pick(el: ReactElement, name: string, data?: unknown) {
  picks.length = 0;
  render(
    <NextIntlClientProvider locale={locale} messages={en} onError={() => {}}>
      {el}
    </NextIntlClientProvider>,
  );
  expect(picks).toHaveLength(1);
  picks[0]!(name, data);
}

const cmp = (golden('compare') as { data: Schemas['Comparison'] }).data;
const pair = { base: cmp.base, other: cmp.other, name: (id: string) => id.toUpperCase() };
const firstGap = cmp.rows.find((r) => r.counted && r.gap)!;
// The golden groups are all too thin; one measured group stands in for the group widgets.
const group: Schemas['Group'] = {
  key: 'Fixture Beauty',
  n: 6,
  status: 'ok',
  reason: null,
  summary: {
    n: 6,
    cheaperCounts: { [cmp.base]: 4, [cmp.other]: 1 },
    equalCount: 1,
    medianGapPct: '3.0',
    meanGapPct: '2.0',
    basket: cmp.summary!.basket,
  },
};
const cross = crossCells(cmp.rows, { min: 1 });
const crossCell = cross.cells[0]!;

const brand = s.brandPrice![0]!.brand;
const node = categoryNodes(s.categoryMix)[0]!;
const bin = histBins(s.priceHist!)[0]!;
const cell = s.promoDepth!.cells[0]!.findIndex((v) => v > 0);

// Each widget: the element with a given onPick, one mark, and the href that mark opens.
const CASES: [string, (onPick?: (href: string) => void) => ReactElement, string, unknown, string][] = [
  [
    'ladder',
    (onPick) => <LadderWidget data={s.ladder!} {...common} onPick={onPick} />,
    s.ladder![0]!.category,
    undefined,
    exploreHref(locale, { category: [s.ladder![0]!.category] }),
  ],
  [
    'promo depth',
    (onPick) => <PromoDepthWidget data={s.promoDepth!} {...common} onPick={onPick} />,
    '',
    [cell, 0, s.promoDepth!.cells[0]![cell]],
    promotionsHref(locale, {
      category: s.promoDepth!.category[0],
      minPct: bandFloor(s.promoDepth!.bands[cell] ?? ''),
    }),
  ],
  [
    'brand price',
    (onPick) => <BrandPriceWidget data={s.brandPrice!} {...common} onPick={onPick} />,
    brand,
    undefined,
    exploreHref(locale, { brand: [brand] }),
  ],
  [
    'brand share',
    (onPick) => <BrandShareWidget data={s.brandPrice!} priced={s.priced!} {...common} onPick={onPick} />,
    brand,
    undefined,
    exploreHref(locale, { brand: [brand] }),
  ],
  [
    'category mix',
    (onPick) => <CategoryMixWidget data={s.categoryMix!} {...common} onPick={onPick} />,
    node.name,
    node,
    categoryNodeHref(locale, node),
  ],
  [
    'top gaps',
    (onPick) => <TopGapsWidget data={cmp.rows} {...common} pair={pair} onPick={onPick} />,
    firstGap.name,
    { id: firstGap.id },
    productHref(locale, firstGap.id),
  ],
  [
    'cross heatmap',
    (onPick) => <CrossHeatmapWidget data={cmp.rows} {...common} pair={pair} onPick={onPick} />,
    '',
    { cell: crossCell },
    compareHref(locale, { ...pair, category: cross.cats[crossCell.row], brand: cross.brands[crossCell.col] }),
  ],
  [
    'cheaper heatmap',
    (onPick) => <CheaperHeatmapWidget data={[group]} {...common} pair={pair} onPick={onPick} />,
    '',
    [0, 0, 4],
    compareHref(locale, { ...pair, groupBy: 'category', category: group.key }),
  ],
  [
    'cheaper share',
    (onPick) => <CheaperShareWidget data={[group]} {...common} pair={pair} groupBy="brand" onPick={onPick} />,
    pair.base,
    { key: group.key },
    compareHref(locale, { ...pair, groupBy: 'brand', brand: group.key }),
  ],
  [
    'group gap',
    (onPick) => <GroupGapWidget data={[group]} {...common} pair={pair} groupBy="category" onPick={onPick} />,
    group.key,
    undefined,
    compareHref(locale, { ...pair, groupBy: 'category', category: group.key }),
  ],
  [
    'price histogram',
    (onPick) => <PriceHistWidget data={s.priceHist!} {...common} onPick={onPick} />,
    '',
    { idx: 0 },
    exploreHref(locale, { priceMin: bin.lo, priceMax: bin.hi, sort: 'price_asc' }),
  ],
];

beforeEach(() => push.mockClear());
afterEach(cleanup);

describe('chart widget drills', () => {
  it.each(CASES)('%s: a mark hands its href to onPick and does not navigate', (_, el, name, data, href) => {
    const onPick = vi.fn();
    pick(el(onPick), name, data);
    expect(onPick).toHaveBeenCalledExactlyOnceWith(href);
    expect(push).not.toHaveBeenCalled();
    expect(href.startsWith('/app')).toBe(false);
  });

  it.each(CASES)('%s: without onPick a mark navigates this tab', (_, el, name, data, href) => {
    pick(el(), name, data);
    expect(push).toHaveBeenCalledExactlyOnceWith(href);
  });
});
