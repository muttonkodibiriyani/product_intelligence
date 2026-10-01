/**
 * A /summary (API 1.4.0) body for the landing tests, checked against `Summary` (#104's SummaryView). Test data only: the app
 * never ships it. Images are null so the run makes no request beyond localhost; the image path is
 * unit-tested.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Summary } from '../lib/api/summary';

const goldenMeta = (
  JSON.parse(readFileSync(join(__dirname, '../../../docs/contracts/golden/pi-api/meta.json'), 'utf8')) as {
    meta: Record<string, unknown>;
  }
).meta;

const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(Number(amount) * 100) });

const cats = [
  'Lipstick',
  'Foundation',
  'Mascara',
  'Moisturizer',
  'Serum',
  'Eau de Parfum',
  'Cleanser',
  'Eyeshadow Palette',
];
const brands = [
  ['Charlotte Tilbury', '185'],
  ['Dior', '240'],
  ['Fenty Beauty', '129'],
  ['Huda Beauty', '115'],
  ['Rare Beauty', '99'],
  ['The Ordinary', '42'],
  ['Clinique', '135'],
  ['Estée Lauder', '210'],
  ['Sol de Janeiro', '95'],
  ['Sephora Collection', '45'],
] as const;

/** With regular prices collected: every widget, promotions included. */
export const summaryBody = {
  status: 'ok',
  data: {
    asOf: '2026-09-30',
    retailer: 'sephora_ae',
    currency: 'AED',
    products: 4812,
    priced: 4790,
    brands: 236,
    categories: 61,
    medianPrice: aed('139.00'),
    promoSharePct: '18.4',
    freshness: { cutoff: '2026-09-30T04:00:00Z', ageDays: 1, status: 'fresh' },
    withheld: [] as Summary['withheld'],
    ladder: cats.map((category, i) => {
      const b = 30 + i * 12;
      return {
        category,
        n: 120 + i * 37,
        min: aed(String(b)),
        p25: aed(String(b * 2)),
        p50: aed(String(b * 3)),
        p75: aed(String(b * 4)),
        max: aed(String(b * 9)),
      };
    }),
    promoDepth: {
      category: cats.slice(0, 6),
      bands: ['10-20', '20-30', '30-50', '50+'],
      cells: [
        [42, 18, 6, 1],
        [30, 22, 9, 0],
        [12, 8, 2, 0],
        [55, 31, 14, 3],
        [40, 26, 11, 2],
        [20, 9, 4, 0],
      ],
    },
    brandPrice: brands.map(([brand, median], i) => ({ brand, n: 210 - i * 15, median: aed(median) })),
    // Category paths, one level deep like Sephora UAE's live categories.
    categoryMix: [
      ['Fragrance', 1120],
      ['Skincare', 1430],
      ['Makeup', 1090],
      ['Hair', 380],
      ['Bath & Body', 292],
      ['Tools & Brushes', 260],
      ['Men', 140],
      ['Gifts', 100],
    ].map(([c, n]) => ({ category: [c as string], n: n as number })),
    priceHist: {
      edges: ['0', '50', '100', '150', '200', '300', '500', '1000'],
      counts: [610, 1140, 1020, 760, 690, 430, 162],
    },
    ratingPrice: {
      n: 4812,
      ratedPct: '62.5',
      sampled: false,
      scale: '5',
      points: Array.from({ length: 60 }, (_, i) => ({
        price: String(25 + ((i * 37) % 600)),
        rating: (3.4 + ((i * 7) % 16) / 10).toFixed(1),
        count: 5 + ((i * 53) % 900),
      })),
    },
    topDiscounts: [
      [
        'p-1',
        'Huda Beauty',
        'Easy Bake Loose Baking & Setting Powder',
        ['Makeup', 'Face', 'Setting Powder'],
        '79.00',
        '158.00',
        '50.0',
      ],
      [
        'p-2',
        'Charlotte Tilbury',
        'Pillow Talk Matte Revolution Lipstick',
        ['Makeup', 'Lips', 'Lipstick'],
        '89.00',
        '160.00',
        '44.4',
      ],
      [
        'p-3',
        'Clinique',
        'Moisture Surge 100H Auto-Replenishing Hydrator 50ml',
        ['Skincare', 'Moisturizers'],
        '115.00',
        '195.00',
        '41.0',
      ],
      ['p-4', 'Dior', 'Sauvage Eau de Parfum 100ml', ['Fragrance', 'Men'], '389.00', '605.00', '35.7'],
      [
        'p-5',
        'Rare Beauty',
        'Soft Pinch Liquid Blush',
        ['Makeup', 'Face', 'Blush'],
        '85.00',
        '125.00',
        '32.0',
      ],
    ].map(([id, brand, name, category, price, regular, depthPct]) => ({
      id: id as string,
      brand: brand as string,
      name: name as string,
      category: category as string[],
      price: aed(price as string),
      regular: aed(regular as string),
      depthPct: depthPct as string,
      image: null,
    })),
  } satisfies Summary,
  // The golden /meta envelope's meta, so the generation matches and nothing is invalidated.
  meta: {
    ...goldenMeta,
    apiVersion: '1.4.0',
    endpoint: '/api/v1/summary',
    filters: { retailer: 'sephora_ae' },
  },
  caveats: [],
};

/** Today's live snapshot: promotions withheld, so their three fields are null. */
export const summaryNoPromo = {
  ...summaryBody,
  data: {
    ...summaryBody.data,
    promoSharePct: null,
    promoDepth: null,
    topDiscounts: null,
    withheld: [{ section: 'promotions', reason: 'capability_off' }],
  } satisfies Summary,
};

/** A blocked retailer, as in the summary-blocked golden: every section withheld, counts null (never 0). */
export const summaryBlocked = {
  ...summaryBody,
  status: 'not_enough_data',
  reason: 'retailer_blocked',
  data: {
    ...summaryBody.data,
    retailer: 'shop_d',
    products: null,
    priced: null,
    brands: null,
    categories: null,
    medianPrice: null,
    ladder: null,
    brandPrice: null,
    categoryMix: null,
    priceHist: null,
    ratingPrice: null,
    promoSharePct: null,
    promoDepth: null,
    topDiscounts: null,
    withheld: (['prices', 'promotions', 'ratings'] as const).map((section) => ({
      section,
      reason: 'retailer_blocked' as const,
    })),
  } satisfies Summary,
};
