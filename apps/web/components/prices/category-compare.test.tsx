import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import {
  THIN,
  categoryCompareBody,
  categoryCompareData,
  wideCategoryCompareBody,
} from '@/e2e/category-compare-fixture';
import { BUCKETS, parseCategoryCompare, type CategoryCompare } from '@/lib/api/category-compare';
import { ApiError } from '@/lib/api/client';
import type { Envelope } from '@/lib/api/types';
import pagesAr from '@/messages/ar.json';
import pagesEn from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgetsEn from '@/messages/widgets.en.json';
import { pairState } from '../widgets/model';
import { CategoryCompareCard, axisTicks } from './category-compare';

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
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
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

  it("reads the served gap as the other retailer's against the base, and says about the same under 1 %", () => {
    show(pairState(ready(), (d) => d.buckets.length > 0));
    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Median gap' })).toBeTruthy();
    const rows = within(table).getAllByRole('row').slice(2);
    const chip = (i: number) => text(within(rows[i]!).getAllByRole('cell').at(-1));
    // Fragrance: the API's −6.0 (395 against 420): Shop B's median is 6 % below Shop A's.
    expect(chip(0)).toBe('Shop B 6% cheaper than Shop A');
    // Lips: the API's +7.4 (102 against 95): Shop B's median is 7.4 % above Shop A's.
    expect(chip(3)).toBe('Shop B 7.4% dearer than Shop A');
    expect(chip(2)).toContain('About the same');
    expect(screen.queryByText(/0% cheaper/)).toBeNull();
  });

  it('keeps a large gap as served: base 50 against other 150 is Shop B 200% dearer, not a 200% discount', () => {
    const good = categoryCompareData('shop_a', 'shop_b', THIN);
    const row = good.rows.find((r) => r.key === 'lips')!;
    const aed = (amount: string) => ({ amount, currency: 'AED', minor: Number(amount.replace('.', '')) });
    const wide = {
      ...row,
      base: { ...row.base, median: aed('50.00') },
      other: { ...row.other, median: aed('150.00') },
      gap: { amount: aed('100.00'), pct: '200.0', cheaper: 'base' },
    };
    const env = {
      ...categoryCompareBody('shop_a', 'shop_b', THIN),
      data: parseCategoryCompare({ ...good, rows: good.rows.map((r) => (r.key === 'lips' ? wide : r)) }),
    } as unknown as Envelope<CategoryCompare>;
    show(pairState(ready(env), (d) => d.buckets.length > 0));
    const lips = within(screen.getByRole('table')).getAllByRole('row')[5]!;
    expect(text(within(lips).getAllByRole('cell').at(-1))).toBe('Shop B 200% dearer than Shop A');
    expect(text(lips)).not.toContain('cheaper');
  });

  it("shows the API's reason when both sides are priced but no gap was sent, and keeps it off the chart and the too-few list", async () => {
    const good = categoryCompareData('shop_a', 'shop_b', THIN);
    const rows = good.rows.map((r) =>
      r.key === 'lips' ? { ...r, gap: null, gapReason: 'currency_mismatch' } : r,
    );
    const d = parseCategoryCompare({ ...good, rows })!;
    const lipsBucket = d.buckets.find((b) => b.key === 'lips')!;
    expect(lipsBucket).toMatchObject({ status: 'no_gap', gapReason: 'currency_mismatch', gapPct: null });
    const env = {
      ...categoryCompareBody('shop_a', 'shop_b', THIN),
      data: d,
    } as unknown as Envelope<CategoryCompare>;
    show(pairState(ready(env), (x) => x.buckets.length > 0));
    const lips = within(screen.getByRole('table')).getAllByRole('row')[5]!;
    expect(text(within(lips).getAllByRole('cell').at(-1))).toBe('Prices are in different currencies.');
    expect(screen.getByText('Too few to compare: Concealer — Shop B n = 3.')).toBeTruthy();
  });

  it('says the figures are category medians, not like-for-like products, in both languages', () => {
    show(pairState(ready(), (d) => d.buckets.length > 0));
    expect(screen.getByText(/not like-for-like products/)).toBeTruthy();
    cleanup();
    show(
      pairState(ready(), (d) => d.buckets.length > 0),
      'ar',
    );
    expect(screen.getByText(/وليس مقارنة بين المنتجات نفسها/)).toBeTruthy();
  });

  it('lists the too-few bucket with its n', () => {
    show(pairState(ready(), (d) => d.buckets.length > 0));
    expect(screen.getByText('Too few to compare: Concealer — Shop B n = 3.')).toBeTruthy();
    expect(screen.getByText("'Other' holds 26.1% of Shop A's products.")).toBeTruthy();
    expect(screen.getByText('Not yet in a category: 2')).toBeTruthy();
    // The API's caveat on the uncategorised products is not a box on this page: it lives under About the data.
    expect(screen.queryByText('12 priced products have no breadcrumb and sit in no category.')).toBeNull();
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('renders in Arabic', () => {
    show(
      pairState(ready(), (d) => d.buckets.length > 0),
      'ar',
    );
    expect(screen.getByText('كيف تقارن الأسعار حسب الفئة؟')).toBeTruthy();
    expect(screen.getAllByText('عدد قليل جدًا (n = 3)').length).toBeGreaterThan(0);
    expect(screen.getAllByText('متقاربان تقريبًا').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Shop B أغلى من Shop A بنسبة 7.4\u200e%\u200e').length).toBeGreaterThan(0);
    const table = screen.getByRole('table');
    expect(text(within(table).getAllByRole('rowheader')[0])).toContain('العطور');
  });

  it.each(['en', 'ar'] as const)(
    'draws the Price range axis over four decades without two labels touching, the currency said once in the head (%s)',
    (locale) => {
      const body = wideCategoryCompareBody();
      const env = { ...body, data: parseCategoryCompare(body.data) } as unknown as Envelope<CategoryCompare>;
      show(
        pairState(ready(env), (d) => d.buckets.length > 0),
        locale,
      );
      const head = screen.getByRole('table').querySelector('thead')!;
      expect(text(head)).toContain(locale === 'ar' ? 'نطاق السعر بـد.إ.' : 'Price range in AED');
      // One axis per retailer; each label sits inside the 120px axis, 6px clear of its neighbour.
      const axes = [...head.querySelectorAll('svg')];
      expect(axes).toHaveLength(2);
      for (const svg of axes) {
        const ticks = [...svg.querySelectorAll('text')].map((el) => ({
          x: Number(el.getAttribute('x')),
          w: text(el).length * 5.5,
          label: text(el),
        }));
        expect(ticks.length).toBeGreaterThanOrEqual(2);
        expect(ticks.every((k) => !/AED|د\.إ/.test(k.label))).toBe(true);
        for (const k of ticks) {
          expect(k.x - k.w / 2).toBeGreaterThanOrEqual(0);
          expect(k.x + k.w / 2).toBeLessThanOrEqual(120);
        }
        const byX = [...ticks].sort((a, b) => a.x - b.x);
        for (let i = 1; i < byX.length; i++)
          expect(byX[i]!.x - byX[i - 1]!.x).toBeGreaterThanOrEqual((byX[i]!.w + byX[i - 1]!.w) / 2 + 6);
      }
    },
  );

  it('thins the axis labels when decades sit closer than a label is wide, and mirrors them in Arabic', () => {
    // Six decades on 120px: 10 to 10M, about 19px a decade.
    const x = (v: number, rtl: boolean) => {
      const px = 4 + ((Math.log10(v) - 1) / 6) * 112;
      return rtl ? 120 - px : px;
    };
    const ticks = [10, 100, 1e3, 1e4, 1e5, 1e6, 1e7];
    const en = axisTicks({ ticks, x }, false, 'en');
    expect(en.map((k) => k.label)).toEqual(['10', '1K', '100K', '10M']);
    const ar = axisTicks({ ticks, x }, true, 'ar');
    // Arabic words are wider ('1 ألف'), so fewer survive; the low end is on the right.
    expect(ar.map((k) => k.label)).toEqual(['10', '1\u00a0ألف', '1\u00a0مليون']);
    expect(ar.map((k) => k.x)).toEqual([...ar.map((k) => k.x)].sort((a, b) => b - a));
    // Three decades fit whole: every label kept.
    const three = (v: number, rtl: boolean) => x(v, rtl) * 2 - 4;
    expect(axisTicks({ ticks: [10, 100, 1e3, 1e4], x: three }, false, 'en').map((k) => k.label)).toEqual([
      '10',
      '100',
      '1K',
      '10K',
    ]);
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

  it('shows unmapped breadcrumb paths as plain text, never as HTML or markdown', () => {
    const body = categoryCompareBody('shop_a', 'shop_b', THIN);
    body.data.unmapped = [
      {
        retailer: 'shop_a',
        path: ['<img src=x onerror=alert(1)>', '**Gift** _sets_'],
        reason: 'no_rule',
        n: 4,
      },
      { retailer: 'shop_b', path: ['العناية', '[link](https://example.com)'], reason: 'ambiguous', n: 2 },
    ];
    const env = { ...body, data: parseCategoryCompare(body.data) } as unknown as Envelope<CategoryCompare>;
    const { container } = show(pairState(ready(env), (d) => d.buckets.length > 0));
    const list = container.querySelector('details ul')!;
    expect(list.querySelector('img, a, strong, em')).toBeNull();
    const paths = [...list.querySelectorAll('bdi')];
    expect(paths.map((b) => b.textContent)).toEqual([
      '<img src=x onerror=alert(1)> › **Gift** _sets_',
      'العناية › [link](https://example.com)',
    ]);
    expect(paths.every((b) => b.getAttribute('dir') === 'auto')).toBe(true);
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
