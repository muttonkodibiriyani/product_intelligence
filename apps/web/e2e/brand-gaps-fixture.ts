/**
 * /brand-gaps and /brand-gaps/items bodies for the gap page's tests (Vitest and Playwright). Test
 * data only: the app never ships it. Ulta against four shops: Sephora and Faces fully collected
 * (proven not-at counts), Ounass partly collected and Bloomingdale's blocked (withheld, no count).
 */
import type { BrandGaps, BrandRow, GapItems } from '../lib/brand-gaps';

const row = (r: Partial<BrandRow> & Pick<BrandRow, 'brand'>): BrandRow => ({
  focusN: 0,
  both: 0,
  unconfirmed: 0,
  family: 0,
  focusOnly: 0,
  bothBy: [],
  notAt: [],
  othersOnly: 0,
  othersBy: [],
  focusOnlyShare: null,
  shareReason: 'cohort_too_small',
  ...r,
});

const shops = (sephora: number, faces: number) => [
  { retailer: 'faces_ae', n: faces },
  { retailer: 'sephora_me', n: sephora },
];

export const gapsData: BrandGaps = {
  focus: 'ulta_ae',
  others: ['bloomingdales_ae', 'faces_ae', 'ounass_ae', 'sephora_me'],
  focusOnlyLabel: 'unmatched',
  absenceLabel: 'unmatched',
  totals: row({
    brand: '',
    focusN: 64,
    both: 33,
    unconfirmed: 4,
    family: 6,
    focusOnly: 21,
    notAt: shops(9, 17),
    othersOnly: 7,
    focusOnlyShare: '32.8',
    shareReason: null,
  }),
  byBrand: [
    row({
      brand: 'Huda Beauty',
      focusN: 12,
      both: 9,
      unconfirmed: 1,
      focusOnly: 2,
      notAt: shops(0, 2),
      othersOnly: 0,
    }),
    row({
      brand: 'Dior',
      focusN: 40,
      both: 22,
      unconfirmed: 3,
      family: 5,
      focusOnly: 10,
      notAt: shops(6, 9),
      othersOnly: 4,
      focusOnlyShare: '25.0',
      shareReason: null,
    }),
    row({
      brand: 'KYLIE COSMETICS',
      focusN: 12,
      both: 2,
      family: 1,
      focusOnly: 9,
      notAt: shops(3, 6),
      othersOnly: 3,
    }),
  ],
  withheld: [
    { retailer: 'bloomingdales_ae', reason: 'retailer_blocked' },
    { retailer: 'ounass_ae', reason: 'retailer_partial' },
  ],
  sides: [
    { retailer: 'ulta_ae', status: 'supported', listings: 64, window: null },
    { retailer: 'sephora_me', status: 'supported', listings: 80, window: null },
    { retailer: 'faces_ae', status: 'supported', listings: 51, window: null },
    { retailer: 'ounass_ae', status: 'partial', listings: 12, window: null },
    { retailer: 'bloomingdales_ae', status: 'blocked', listings: 0, window: null },
  ],
};

export const gapItems: GapItems = {
  total: 2,
  nextCursor: null,
  items: [
    {
      id: 'p-dior-1',
      brand: 'Dior',
      name: 'Rouge Dior Lipstick 999',
      category: ['Makeup', 'Lips'],
      retailer: 'ulta_ae',
      side: 'focus_only',
      bothAt: [],
      notAt: ['faces_ae', 'sephora_me'],
    },
    {
      id: 'p-dior-2',
      brand: 'Dior',
      name: 'Forever Skin Glow Foundation 30ml',
      category: ['Makeup', 'Face'],
      retailer: 'ulta_ae',
      side: 'focus_only',
      bothAt: [],
      notAt: ['faces_ae'],
    },
  ],
};
