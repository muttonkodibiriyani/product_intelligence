import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { THIN, categoryCompareBody } from '@/e2e/category-compare-fixture';
import { parseCategoryCompare, type CategoryCompare } from '@/lib/api/category-compare';
import type { Envelope } from '@/lib/api/types';
import pagesAr from '@/messages/ar.json';
import pagesEn from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgetsEn from '@/messages/widgets.en.json';
import type { PairState } from '../widgets/use-compare';
import { CategoryHeadToHead } from './category-head-to-head';

const en = { ...pagesEn, widgets: widgetsEn };
const ar = { ...pagesAr, widgets: widgetsAr };
const pair = {
  base: 'shop_a',
  other: 'shop_b',
  name: (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id,
};

const ready = (): PairState<CategoryCompare> => {
  const body = categoryCompareBody('shop_a', 'shop_b', THIN);
  const env = { ...body, data: parseCategoryCompare(body.data) } as unknown as Envelope<CategoryCompare>;
  return { kind: 'ready', data: env.data!, env };
};

function show(state: PairState<CategoryCompare>, locale: 'en' | 'ar' = 'en') {
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      <CategoryHeadToHead state={state} pair={pair} />
    </NextIntlClientProvider>,
  );
  const row = (label: string) => screen.getByRole('row', { name: new RegExp(`^${label}`) });
  return { row };
}

afterEach(cleanup);

describe('CategoryHeadToHead', () => {
  it('one row per bucket, the medians as sent, the gap bar toward the cheaper side', () => {
    const { row } = show(ready());
    expect(screen.getByRole('heading', { level: 2, name: 'Where each shop is cheaper' })).toBeTruthy();
    expect(screen.getAllByRole('rowheader')).toHaveLength(9);
    const fragrance = row('Fragrance');
    expect(fragrance.textContent).toContain('420.00');
    expect(fragrance.textContent).toContain('395.00');
    expect(fragrance.textContent).toContain('-6.0%');
    // Shop B (other) is cheaper: the fill runs toward the start in Shop B's colour, and says so.
    const fill = fragrance.querySelector('.gapbar i')!;
    expect(fill.getAttribute('data-shop')).toBe('shop_b');
    expect(fill.getAttribute('data-at')).toBe('start');
    expect(fill.getAttribute('style')).toContain('background: var(--color-series-b');
    expect(fragrance.textContent).toContain('Shop B cheaper');
    const lips = row('Lips');
    expect(lips.textContent).toContain('+7.4%');
    expect(lips.querySelector('.gapbar i')?.getAttribute('data-shop')).toBe('shop_a');
    expect(lips.querySelector('.gapbar i')?.getAttribute('data-at')).toBe('end');
    expect(lips.querySelector('.gapbar i')?.getAttribute('style')).toContain(
      'background: var(--color-series-a',
    );
    expect(lips.textContent).toContain('Shop A cheaper');
    // No value judgement: the fill is never the good or bad tone.
    expect(document.querySelector('[data-side], .text-good, .text-bad')).toBeNull();
    // Body has the widest gap on the table (concealer is too few), so its fill takes the whole half.
    expect(row('Body').querySelector('.gapbar i')?.getAttribute('style')).toContain('width: 50%');
  });

  it('the foot names the minimum and the unmapped count in the right number, in both languages', () => {
    show(ready());
    expect(screen.getByText(/A side needs at least 5 priced products/)).toBeTruthy();
    expect(screen.getByText(/Not yet in a category: 301 products\./)).toBeTruthy();
    cleanup();
    show(ready(), 'ar');
    expect(screen.getByText(/يحتاج كل طرف إلى 5 منتجات مسعّرة على الأقل/)).toBeTruthy();
    expect(screen.getByText(/لم تُصنَّف بعد: 301 منتج\./)).toBeTruthy();
  });

  it('a bucket the API calls the same is "same", not a tiny gap', () => {
    const { row } = show(ready());
    const eyes = row('Eyes');
    expect(eyes.textContent).toContain('same');
    expect(eyes.textContent).not.toContain('%');
    expect(eyes.querySelector('.gapbar i')).toBeNull();
  });

  it('a too-few side shows its count in place of a median, and no gap', () => {
    const { row } = show(ready());
    const concealer = row('Concealer');
    expect(concealer.textContent).toContain('too few (n = 3)');
    expect(concealer.textContent).toContain('–');
    expect(concealer.textContent).not.toContain('%');
  });

  it('a side the API left out is "not available", never a count of 0 or too few (n = 0)', () => {
    const r = ready() as Extract<PairState<CategoryCompare>, { kind: 'ready' }>;
    const buckets = r.data.buckets.map((b) =>
      b.key === 'cheek'
        ? { ...b, sides: { shop_a: b.sides.shop_a! }, status: 'too_few' as const, gapPct: null }
        : b,
    );
    const { row } = show({ ...r, data: { ...r.data, buckets } });
    const cheek = row('Cheek');
    expect(cheek.textContent).toContain('not available');
    expect(cheek.textContent).not.toContain('n = 0');
    expect(cheek.textContent).not.toMatch(/Shop B\s*0/);
    expect(cheek.querySelectorAll('td:nth-child(2) i')).toHaveLength(1);
    expect(cheek.textContent).not.toContain('%');
  });

  it('counts sit behind the bars for screen readers, both shops named', () => {
    const { row } = show(ready());
    const fragrance = row('Fragrance');
    expect(within(fragrance).getByText('Shop A', { exact: false })).toBeTruthy();
    expect(fragrance.textContent).toMatch(/Shop A\s*\d/);
  });

  it('empty and error states say so without a number', () => {
    show({ kind: 'empty', env: null });
    expect(screen.getByRole('note').textContent).toContain('Category comparison is not available yet.');
    cleanup();
    show({ kind: 'error', error: new Error('x'), retry: () => {} });
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: /retry|try again/i })).toBeTruthy();
  });

  it('in Arabic', () => {
    const { row } = show(ready(), 'ar');
    expect(screen.getByRole('heading', { level: 2, name: 'أين يكون كل متجر أرخص' })).toBeTruthy();
    expect(row('العطور').textContent).toContain('395.00');
  });
});
