/**
 * A /category-compare body for the tests, in DC's wire shape (CategoryComparison / CategoryRow /
 * Cell / Coverage / UnmappedPath), which lib/api/category-compare.ts reads into the app's model.
 *
 * SAMPLE DATA: the product counts per bucket are the live Sephora/Ulta counts at the time of
 * writing; every price (median, mean, quartiles, min, max, gap) is made up to be plausible in AED,
 * and Ulta's concealer side is overridden to n = 3 so the too-few path is exercised. The app never
 * ships this file.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { BUCKETS, type BucketKey } from '../lib/api/category-compare';

const goldenMeta = (
  JSON.parse(readFileSync(join(__dirname, '../../../docs/contracts/golden/pi-api/meta.json'), 'utf8')) as {
    meta: Record<string, unknown>;
  }
).meta;

const aed = (amount: number) => ({
  amount: amount.toFixed(2),
  currency: 'AED',
  minor: Math.round(amount * 100),
});

/** Live counts (base, other) and sample medians (base, other) per bucket. */
const ROWS: Record<BucketKey, { n: [number, number]; median: [number, number]; label: [string, string] }> = {
  fragrance: { n: [2586, 1459], median: [420, 395], label: ['Fragrance', 'العطور'] },
  skincare: { n: [2139, 1835], median: [185, 172], label: ['Skincare', 'العناية بالبشرة'] },
  eyes: { n: [661, 829], median: [120, 119], label: ['Eyes', 'العيون'] },
  lips: { n: [625, 522], median: [95, 102], label: ['Lips', 'الشفاه'] },
  body: { n: [618, 440], median: [110, 98], label: ['Body', 'الجسم'] },
  cheek: { n: [174, 118], median: [140, 150], label: ['Cheek', 'الخدود'] },
  foundation: { n: [136, 135], median: [165, 160], label: ['Foundation', 'كريم الأساس'] },
  concealer: { n: [104, 3], median: [110, 95], label: ['Concealer', 'الكونسيلر'] },
  other: { n: [2486, 1870], median: [95, 88], label: ['Other', 'أخرى'] },
};

const MIN_COHORT = 5;

/** A wire Cell with a plausible spread: quartiles at ±35 %, whiskers at ÷4 and ×6. */
function cell(retailer: string, n: number, median: number, withMean = true) {
  if (n < MIN_COHORT)
    return {
      retailer,
      n,
      tooFew: true,
      reason: 'cohort_too_small',
      median: null,
      mean: null,
      p25: null,
      p75: null,
      min: null,
      max: null,
    };
  return {
    retailer,
    n,
    tooFew: false,
    reason: null,
    median: aed(median),
    mean: withMean ? aed(median * 1.18) : null,
    p25: aed(median * 0.65),
    p75: aed(median * 1.35),
    min: aed(median / 4),
    max: aed(median * 6),
  };
}

/** The CategoryComparison for a pair, rows ranked by the smaller count as the API sends them. */
export function categoryCompareData(base = 'shop_a', other = 'shop_b') {
  const rows = BUCKETS.map((key) => {
    const r = ROWS[key];
    const a = cell(base, r.n[0], r.median[0]);
    // 'body' has no mean on the other side, so the UI's "omit a null mean" path is covered too.
    const b = cell(other, r.n[1], r.median[1], key !== 'body');
    const ok = !a.tooFew && !b.tooFew;
    const pct = ok ? ((r.median[1] - r.median[0]) / r.median[0]) * 100 : null;
    return {
      key,
      label: { en: r.label[0], ar: r.label[1] },
      base: a,
      other: b,
      shared: true,
      gap:
        pct === null
          ? null
          : {
              amount: aed(r.median[1] - r.median[0]),
              pct: pct.toFixed(1),
              cheaper: Math.abs(pct) < 1 ? 'equal' : pct > 0 ? 'base' : 'other',
            },
      gapReason: ok ? null : 'cohort_too_small',
    };
  });
  rows.sort((x, y) => Math.min(y.base.n, y.other.n) - Math.min(x.base.n, x.other.n));
  const total = (i: 0 | 1) => BUCKETS.reduce((s, k) => s + ROWS[k].n[i], 0);
  const coverage = (retailer: string, i: 0 | 1, unmapped: number, noBreadcrumb: number) => {
    const mapped = total(i);
    return {
      retailer,
      priced: mapped + unmapped + noBreadcrumb,
      mapped,
      unmapped,
      noBreadcrumb,
      otherBucket: ROWS.other.n[i],
      otherPct: ((ROWS.other.n[i] / mapped) * 100).toFixed(1),
    };
  };
  return {
    base,
    other,
    level: 'bucket',
    taxonomy: 'taxonomy@1',
    minCohort: MIN_COHORT,
    rows,
    coverage: { base: coverage(base, 0, 260, 12), other: coverage(other, 1, 41, 0) },
    unmapped: [
      { retailer: base, path: ['Tools & Brushes'], reason: 'no_rule', n: 260 },
      { retailer: other, path: ['Wellness', 'Supplements'], reason: 'no_rule', n: 41 },
    ],
    unmappedPaths: 2,
    convention: 'other_vs_base_median_pct',
  };
}

/** The whole envelope, with the golden /meta's meta block and the pair-scoped caveats. */
export function categoryCompareBody(base = 'shop_a', other = 'shop_b') {
  return {
    status: 'ok',
    data: categoryCompareData(base, other),
    meta: {
      ...goldenMeta,
      endpoint: '/api/v1/category-compare',
      cutoff: '2026-09-30T04:00:00Z',
      filters: { retailers: `${base},${other}`, level: 'bucket' },
    },
    caveats: [
      {
        code: 'breadcrumb_missing',
        params: { retailer: base },
        en: '12 priced products have no breadcrumb and sit in no category.',
        ar: '12 منتجًا مسعّرًا بلا مسار تصنيف ولا تندرج تحت أي فئة.',
      },
    ],
    cohort: null,
    reason: null,
    detail: null,
  };
}
