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
import { retailerColor } from '../ui/retailer-dot';
import type { PairState } from '../widgets/use-compare';
import { CategoryHeadToHead, rankBuckets } from './category-head-to-head';

const en = { ...pagesEn, widgets: widgetsEn };
const ar = { ...pagesAr, widgets: widgetsAr };
const pair = {
  base: 'shop_a',
  other: 'shop_b',
  name: (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id,
};

const ready = (): Extract<PairState<CategoryCompare>, { kind: 'ready' }> => {
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
  it('the title is the finding, from the API’s own cheaper verdicts; the method is a tooltip', () => {
    show(ready());
    // Shop B is cheaper in 5 of the 8 compared buckets (concealer is too few, eyes the same).
    expect(
      screen.getByRole('heading', { level: 2, name: 'Shop B cheaper in 5 of 8 categories' }),
    ).toBeTruthy();
    expect(screen.getByText('Where each shop is cheaper')).toBeTruthy();
    const tip = screen.getByRole('tooltip').textContent!;
    expect(tip).toMatch(/^Bars are product counts/);
    expect(tip).toContain('A side needs at least 5 priced products');
    expect(tip).toContain('Not yet in a category: 301 products.');
    expect(tip).toContain('Prices in AED.');
    // No foot paragraph of prose under the table.
    expect(document.querySelectorAll('section p')).toHaveLength(1); // the meta line only
    expect(screen.getByRole('link', { name: 'Open prices' }).getAttribute('href')).toMatch(/\/prices\/?$/);
  });

  it('one row per bucket, widest gap first, the medians and counts as sent, the gap bar toward the cheaper side', () => {
    const { row } = show(ready());
    const heads = screen.getAllByRole('rowheader').map((h) => h.textContent);
    expect(heads).toHaveLength(9);
    // Body carries the widest gap, so it leads; too few (Concealer) sits last.
    expect(heads[0]).toBe('Body');
    expect(heads[8]).toBe('Concealer');
    const fragrance = row('Fragrance');
    expect(fragrance.textContent).toContain('420.00');
    expect(fragrance.textContent).toContain('395.00');
    expect(fragrance.textContent).toContain('-6.0%');
    expect(fragrance.textContent).toContain('n = 2,586');
    // Shop B (other) is cheaper: the fill runs toward the start in Shop B's colour (the same table
    // its dot uses); the chip names it for screen readers.
    const fill = fragrance.querySelector('.gapbar i')!;
    expect(fill.getAttribute('data-shop')).toBe('shop_b');
    expect(fill.getAttribute('data-at')).toBe('start');
    expect(fill.getAttribute('style')).toContain(`background: ${retailerColor('shop_b', 1)}`);
    expect(within(fragrance).getByText('Shop B cheaper')).toBeTruthy();
    const lips = row('Lips');
    expect(lips.textContent).toContain('+7.4%');
    expect(lips.querySelector('.gapbar i')?.getAttribute('data-shop')).toBe('shop_a');
    expect(lips.querySelector('.gapbar i')?.getAttribute('data-at')).toBe('end');
    // No value judgement: the fill is never the good or bad tone.
    expect(document.querySelector('[data-side], .text-good, .text-bad')).toBeNull();
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

  it('a side the API left out is "not available", never a count of 0 or too few (n = 0)', () => {
    const r = ready();
    const buckets = r.data.buckets.map((b) =>
      b.key === 'cheek'
        ? { ...b, sides: { shop_a: b.sides.shop_a! }, status: 'too_few' as const, gapPct: null }
        : b,
    );
    const { row } = show({ ...r, data: { ...r.data, buckets } });
    const cheek = row('Cheek');
    expect(cheek.textContent).toContain('not available');
    expect(cheek.textContent).not.toContain('n = 0');
    expect(cheek.textContent).not.toMatch(/Shop B\s*n/);
    expect(cheek.textContent).not.toContain('%');
  });

  it('a tie and an all-same read say so in the title', () => {
    const r = ready();
    // The 8 ok buckets split 4/4 (concealer stays too few).
    let k = 0;
    const tie = r.data.buckets.map((b) =>
      b.status === 'ok'
        ? { ...b, cheaper: k++ < 4 ? 'shop_a' : 'shop_b', gapPct: k <= 4 ? '5.0' : '-5.0' }
        : b,
    );
    show({ ...r, data: { ...r.data, buckets: tie } });
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe(
      'Shop A and Shop B each cheaper in 4 of 8 categories',
    );
    cleanup();
    const same = r.data.buckets.map((b) =>
      b.status === 'ok' ? { ...b, cheaper: 'same', gapPct: '0.0' } : b,
    );
    show({ ...r, data: { ...r.data, buckets: same } });
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Same median in all 8 categories');
  });

  it('empty and error states say so without a number, under the plain title', () => {
    show({ kind: 'empty', env: null });
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Where each shop is cheaper');
    expect(screen.getByRole('note').textContent).toContain('Category comparison is not available yet.');
    expect(screen.queryByRole('tooltip')).toBeNull();
    cleanup();
    show({ kind: 'error', error: new Error('x'), retry: () => {} });
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: /retry|try again/i })).toBeTruthy();
  });

  it('in Arabic, with Latin digits', () => {
    const { row } = show(ready(), 'ar');
    expect(screen.getByRole('heading', { level: 2, name: 'Shop B أرخص في 5 من 8 فئات' })).toBeTruthy();
    expect(row('العطور').textContent).toContain('395.00');
    expect(screen.getByRole('tooltip').textContent).toContain('يحتاج كل طرف إلى 5 منتجات مسعّرة على الأقل');
    expect(document.body.textContent).not.toMatch(/[٠-٩]/);
  });
});

describe('rankBuckets', () => {
  it('widest gap first, rows without a gap after in the API’s order', () => {
    const keys = rankBuckets(ready().data.buckets).map((b) => `${b.key}:${b.gapPct ?? '-'}`);
    const gaps = keys.filter((k) => !k.endsWith(':-')).map((k) => Math.abs(Number(k.split(':')[1])));
    expect(gaps).toEqual([...gaps].sort((a, b) => b - a));
    expect(keys[keys.length - 1]).toBe('concealer:-');
  });
});
