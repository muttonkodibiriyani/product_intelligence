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
    // Shop B (other) is cheaper: the fill reads as good and runs toward the start.
    expect(fragrance.querySelector('.gapbar i')?.getAttribute('data-side')).toBe('good');
    const lips = row('Lips');
    expect(lips.textContent).toContain('+7.4%');
    expect(lips.querySelector('.gapbar i')?.getAttribute('data-side')).toBe('bad');
    // Body has the widest gap on the table (concealer is too few), so its fill takes the whole half.
    expect(row('Body').querySelector('.gapbar i')?.getAttribute('style')).toContain('width: 50%');
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
