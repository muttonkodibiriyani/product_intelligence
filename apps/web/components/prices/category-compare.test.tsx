import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { THIN, categoryCompareBody, categoryCompareData } from '@/e2e/category-compare-fixture';
import { BUCKETS, parseCategoryCompare, type Bucket, type CategoryCompare } from '@/lib/api/category-compare';
import { ApiError } from '@/lib/api/client';
import type { Envelope } from '@/lib/api/types';
import pagesAr from '@/messages/ar.json';
import pagesEn from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgetsEn from '@/messages/widgets.en.json';
import { pairState } from '../widgets/model';
import { CategoryCompareCard } from './category-compare';

// The chart is ECharts; here it only records which buckets it was handed.
const charted: Bucket[][] = [];
vi.mock('../widgets/charts', () => ({
  BucketGapWidget: ({ data }: { data: Bucket[] }) => {
    charted.push(data);
    return <div data-testid="bucket-chart" />;
  },
}));

const en = { ...pagesEn, widgets: widgetsEn };
const ar = { ...pagesAr, widgets: widgetsAr };
const pair = {
  base: 'shop_a',
  other: 'shop_b',
  name: (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id,
};

const parsed = () => parseCategoryCompare(categoryCompareData('shop_a', 'shop_b', THIN))!;
const envelope = (): Envelope<CategoryCompare> => {
  const body = categoryCompareBody('shop_a', 'shop_b', THIN);
  return { ...body, data: parseCategoryCompare(body.data) } as unknown as Envelope<CategoryCompare>;
};
type Q = Parameters<typeof pairState<CategoryCompare>>[0];
const ready = (env = envelope()): Q => ({ data: env, isError: false, error: null, refetch: () => {} });

function show(state: ReturnType<typeof pairState<CategoryCompare>>, locale: 'en' | 'ar' = 'en') {
  charted.length = 0;
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      <CategoryCompareCard state={state} pair={pair} locale={locale} />
    </NextIntlClientProvider>,
  );
}

afterEach(cleanup);

const text = (el: Element | null | undefined) => el?.textContent ?? '';

describe('parseCategoryCompare', () => {
  it('reads a good body into the nine buckets in the fixed order, whatever order the API ranked them', () => {
    const raw = categoryCompareData('shop_a', 'shop_b', THIN);
    expect(raw.rows.map((r) => r.key)).not.toEqual([...BUCKETS]);
    const d = parsed();
    expect(d.retailers).toEqual(['shop_a', 'shop_b']);
    expect(d.minN).toBe(5);
    expect(d.buckets.map((b) => b.key)).toEqual([...BUCKETS]);
    const fragrance = d.buckets[0]!;
    expect(fragrance.status).toBe('ok');
    expect(fragrance.sides.shop_a!.n).toBe(2586);
    expect(fragrance.sides.shop_b!.median!.amount).toBe('395.00');
    // other − base over base: 395 vs 420 is −6.0 %, so `other` is cheaper.
    expect(fragrance.gapPct).toBe('-6.0');
    expect(fragrance.cheaper).toBe('shop_b');
    expect(fragrance.gapAmount!.amount).toBe('-25.00');
    expect(d.otherShare).toEqual({ shop_a: expect.any(String), shop_b: expect.any(String) });
    expect(d.unmapped[1]).toEqual({
      retailer: 'shop_b',
      category: 'Wellness › Supplements',
      reason: 'no_rule',
      n: 41,
    });
    expect(d.unmappedPaths).toBe(2);
  });

  it('keeps a too-few side with its count and suppresses the gap, never 0', () => {
    const concealer = parsed().buckets.find((b) => b.key === 'concealer')!;
    expect(concealer.status).toBe('too_few');
    expect(concealer.sides.shop_a!.status).toBe('ok');
    expect(concealer.sides.shop_b).toMatchObject({ status: 'too_few', n: 3, median: null, mean: null });
    expect(concealer.gapPct).toBeNull();
    expect(concealer.cheaper).toBeNull();
  });

  it('keeps a null mean as null', () => {
    const body = parsed().buckets.find((b) => b.key === 'body')!;
    expect(body.sides.shop_a!.mean).not.toBeNull();
    expect(body.sides.shop_b!.mean).toBeNull();
  });

  it('rejects a body that is not the contract', () => {
    const good = categoryCompareData('shop_a', 'shop_b', THIN);
    expect(parseCategoryCompare(null)).toBeNull();
    expect(parseCategoryCompare([])).toBeNull();
    expect(parseCategoryCompare({ ...good, level: 'subcategory' })).toBeNull();
    expect(parseCategoryCompare({ ...good, rows: 'nope' })).toBeNull();
    expect(parseCategoryCompare({ ...good, other: 'shop_a' })).toBeNull();
    expect(parseCategoryCompare({ ...good, base: undefined })).toBeNull();
  });

  it('fills a missing row as too few on both sides, with nothing dropped', () => {
    const good = categoryCompareData('shop_a', 'shop_b', THIN);
    const d = parseCategoryCompare({ ...good, rows: good.rows.filter((r) => r.key !== 'lips') })!;
    expect(d.buckets).toHaveLength(9);
    const lips = d.buckets[3]!;
    expect(lips.key).toBe('lips');
    expect(lips.status).toBe('too_few');
    expect(lips.sides.shop_a).toMatchObject({ status: 'too_few', n: 0, median: null });
    expect(lips.sides.shop_b).toMatchObject({ status: 'too_few', n: 0, median: null });
    expect(lips.gapPct).toBeNull();
  });

  it("maps cheaper 'base' / 'other' / 'equal' to the ids and 'same'", () => {
    const d = parsed();
    const by = (k: string) => d.buckets.find((b) => b.key === k)!;
    expect(by('lips').cheaper).toBe('shop_a'); // 102 vs 95: other dearer, base cheaper
    expect(by('fragrance').cheaper).toBe('shop_b');
    expect(by('eyes').cheaper).toBe('same'); // 119 vs 120: under 1 %
  });

  it('reads a blocked retailer as blocked, not too few, and withholds the gap', () => {
    const good = categoryCompareData('shop_a', 'shop_b', THIN);
    const row = good.rows.find((r) => r.key === 'lips')!;
    const blockedRow = {
      ...row,
      other: { ...row.other, tooFew: true, reason: 'retailer_blocked', median: null },
      gap: null,
      gapReason: 'retailer_blocked',
    };
    const d = parseCategoryCompare({
      ...good,
      rows: good.rows.map((r) => (r.key === 'lips' ? blockedRow : r)),
    })!;
    const lips = d.buckets.find((b) => b.key === 'lips')!;
    expect(lips.status).toBe('blocked');
    expect(lips.sides.shop_b).toMatchObject({ status: 'blocked', reason: 'retailer_blocked' });
    expect(lips.sides.shop_a!.status).toBe('ok');
    expect(lips.gapPct).toBeNull();
  });
});

describe('CategoryCompareCard', () => {
  it('renders the nine buckets in order, the too-few side in words with its n, and a dash for its gap', async () => {
    show(pairState(ready(), (d) => d.buckets.length > 0, { notFoundIsEmpty: true }));
    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row').slice(2); // two header rows
    expect(rows.map((r) => within(r).getByRole('rowheader').textContent)).toEqual([
      'Fragrance',
      'Skincare',
      'Eyes',
      'Lips',
      'Body',
      'Cheek',
      'Foundation',
      'Concealer',
      'Other',
    ]);
    const concealer = rows[7]!;
    expect(text(concealer)).toContain('too few (n = 3)');
    const cells = within(concealer).getAllByRole('cell');
    // n, median, range for Shop A; one too-few note across Shop B's three columns, its n said once; then the chip.
    expect(cells).toHaveLength(5);
    expect(cells[3]!.getAttribute('colspan')).toBe('3');
    expect(text(cells[3])).toBe('too few (n = 3)');
    expect(cells[3]!.querySelector('svg')).toBeNull();
    expect(text(cells[4])).toBe('–');
    expect(screen.getByText('Full catalogues · 9 shared categories · 30 Sept 2026')).toBeTruthy();
    expect(await screen.findByTestId('bucket-chart')).toBeTruthy();
  });

  it('omits a null mean instead of showing 0', () => {
    show(pairState(ready(), (d) => d.buckets.length > 0));
    const table = screen.getByRole('table');
    const body = within(table).getAllByRole('row')[6]!;
    const cells = within(body).getAllByRole('cell');
    expect(text(cells[1])).toContain('mean');
    expect(text(cells[4])).not.toContain('mean');
    expect(text(cells[4])).not.toContain('0.00');
    expect(text(cells[4])).toMatch(/AED\s98\.00/);
  });

  it('names the cheaper retailer with the gap size, and says about the same under 1 %', () => {
    show(pairState(ready(), (d) => d.buckets.length > 0));
    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row').slice(2);
    // Fragrance: 395 against 420 is −6 %, so Shop B (other) is cheaper.
    expect(text(within(rows[0]!).getAllByRole('cell').at(-1))).toContain('Shop B 6% cheaper');
    // Lips: 102 against 95 is +7.4 %, so Shop A (base) is cheaper.
    expect(text(within(rows[3]!).getAllByRole('cell').at(-1))).toContain('Shop A 7.4% cheaper');
    expect(text(within(rows[2]!).getAllByRole('cell').at(-1))).toContain('About the same');
    expect(screen.queryByText(/0% cheaper/)).toBeNull();
  });

  it('leaves the too-few bucket out of the chart and lists it with its n', async () => {
    show(pairState(ready(), (d) => d.buckets.length > 0));
    await screen.findByTestId('bucket-chart');
    expect(charted.at(-1)!.map((b) => b.key)).toEqual(BUCKETS.filter((k) => k !== 'concealer'));
    expect(screen.getByText('Too few to compare: Concealer — Shop B n = 3.')).toBeTruthy();
    expect(screen.getByText("'Other' holds 26.1% of Shop A's products.")).toBeTruthy();
    expect(screen.getByText('Not yet in a category: 2')).toBeTruthy();
    expect(screen.getByText('12 priced products have no breadcrumb and sit in no category.')).toBeTruthy();
  });

  it('renders in Arabic', () => {
    show(
      pairState(ready(), (d) => d.buckets.length > 0),
      'ar',
    );
    expect(screen.getByText('كيف تقارن الأسعار حسب الفئة؟')).toBeTruthy();
    expect(screen.getAllByText('عدد قليل جدًا (n = 3)').length).toBeGreaterThan(0);
    expect(screen.getAllByText('متقاربان تقريبًا').length).toBeGreaterThan(0);
    const table = screen.getByRole('table');
    expect(text(within(table).getAllByRole('rowheader')[0])).toContain('العطور');
  });

  it('shows the blocked side as withheld, in the reason wording, not as too few', () => {
    const good = categoryCompareData('shop_a', 'shop_b', THIN);
    const row = good.rows.find((r) => r.key === 'lips')!;
    const blocked = {
      ...good,
      rows: good.rows.map((r) =>
        r.key === 'lips'
          ? {
              ...row,
              other: { ...row.other, tooFew: true, reason: 'retailer_blocked', median: null },
              gap: null,
            }
          : r,
      ),
    };
    const env = {
      ...categoryCompareBody('shop_a', 'shop_b', THIN),
      data: parseCategoryCompare(blocked),
    } as unknown as Envelope<CategoryCompare>;
    show(pairState(ready(env), (d) => d.buckets.length > 0));
    const lips = within(screen.getByRole('table')).getAllByRole('row')[5]!;
    expect(text(lips)).toContain('This retailer blocks collection.');
    expect(text(lips)).not.toContain('too few');
    expect(screen.getByText(/^Withheld: Lips — Shop B\./)).toBeTruthy();
  });

  it('shows a 404 as not available yet, not as an error', () => {
    const q: Q = {
      data: undefined,
      isError: true,
      error: new ApiError('not_found', 404),
      refetch: () => {},
    };
    show(pairState(q, (d) => d.buckets.length > 0, { notFoundIsEmpty: true }));
    expect(text(screen.getByRole('note'))).toContain('Category comparison is not available yet.');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
