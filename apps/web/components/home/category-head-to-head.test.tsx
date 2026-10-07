import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import {
  THIN,
  categoryCompareBody,
  compareGroups,
  type Counts,
  type GroupCounts,
} from '@/e2e/category-compare-fixture';
import { BUCKETS, parseCategoryCompare, type CategoryCompare } from '@/lib/api/category-compare';
import type { Envelope, Schemas } from '@/lib/api/types';
import pagesAr from '@/messages/ar.json';
import pagesEn from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgetsEn from '@/messages/widgets.en.json';
import { retailerColor } from '../ui/retailer-dot';
import type { PairState } from '../widgets/use-compare';
import { CategoryHeadToHead, hasCategoryRows } from './category-head-to-head';

const en = { ...pagesEn, widgets: widgetsEn };
const ar = { ...pagesAr, widgets: widgetsAr };
const pair = {
  base: 'shop_a',
  other: 'shop_b',
  name: (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id,
};

/** Shop B cheaper on more matched pairs in fragrance and lips, Shop A in skincare; cheek is thin. */
const GROUPS: GroupCounts = { fragrance: [10, 30, 2], skincare: [12, 4, 0], lips: [3, 9, 1], cheek: 3 };
const groups = (c: GroupCounts = GROUPS) => compareGroups('shop_a', 'shop_b', c) as Schemas['Group'][];

const envelope = (counts: Counts, status = 'ok') => {
  const body = categoryCompareBody('shop_a', 'shop_b', counts);
  return { ...body, status, data: parseCategoryCompare(body.data) } as unknown as Envelope<CategoryCompare>;
};
const ready = (counts: Counts = THIN): Extract<PairState<CategoryCompare>, { kind: 'ready' }> => {
  const env = envelope(counts);
  return { kind: 'ready', data: env.data!, env };
};
/** Live on 2026-10-06: Ulta read on Faces' date, so no price in any bucket and no gap anywhere. */
const stale = (): PairState<CategoryCompare> => ({
  kind: 'empty',
  env: envelope(Object.fromEntries(BUCKETS.map((k) => [k, [0, 120]])), 'not_enough_data'),
});

function show(
  state: PairState<CategoryCompare>,
  g: readonly Schemas['Group'][] | null = groups(),
  locale: 'en' | 'ar' = 'en',
) {
  const { container } = render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      <CategoryHeadToHead state={state} groups={g} pair={pair} />
    </NextIntlClientProvider>,
  );
  const row = (label: string) =>
    screen.getByRole<HTMLTableRowElement>('row', { name: new RegExp(`^${label}`) });
  const tipOf = (el: HTMLElement) =>
    document.getElementById(el.getAttribute('aria-describedby')!)!.textContent;
  return { row, tipOf, container };
}

/** What a cell shows on screen: its tooltip trigger's text when it has one, not the bubble's. */
const face = (cell: Element) => (cell.querySelector('[aria-describedby]') ?? cell).textContent;

afterEach(cleanup);

describe('CategoryHeadToHead', () => {
  it('the title is the matched finding, never the medians; the method is a tooltip', () => {
    const { tipOf } = show(ready());
    // Shop B wins fragrance and lips on the same products, Shop A skincare; cheek is thin.
    expect(
      screen.getByRole('heading', { level: 2, name: 'Same product cheaper at Shop B in 2 of 3 categories' }),
    ).toBeTruthy();
    expect(screen.getByText('Where each shop is cheaper')).toBeTruthy();
    const about = tipOf(screen.getByText('About').parentElement!);
    expect(about).toMatch(/^Typical price is each shop’s median over everything it prices/);
    expect(about).toContain('A side needs at least 5 priced products');
    expect(about).toContain('Not yet in a category: 301 products.');
    expect(about).toContain('Prices in AED.');
    // The medians are labelled for what they are, with the range-mix caveat behind the label.
    const typical = screen.getByText('Typical price (whole range)');
    expect(typical.closest('th')?.getAttribute('scope')).toBe('colgroup');
    expect(tipOf(typical.parentElement!)).toContain('does not mean cheaper');
    expect(screen.getByRole('columnheader', { name: 'Same product cheaper at' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open prices' }).getAttribute('href')).toMatch(/\/prices\/?$/);
  });

  it('rows rank by the range gap; the bar is toward the lower typical price and never says cheaper', () => {
    const { row } = show(ready());
    const heads = screen.getAllByRole('rowheader').map((h) => h.textContent);
    // Concealer has no gap (too few) and no matched group: it folds into the last row.
    expect(heads).toHaveLength(8);
    expect(heads[0]).toBe('Body');
    expect(heads).not.toContain('Concealer');
    const fragrance = row('Fragrance');
    expect(fragrance.textContent).toContain('420.00');
    expect(fragrance.textContent).toContain('395.00');
    expect(fragrance.textContent).toContain('-6.0%');
    expect(fragrance.textContent).toContain('n = 2,586');
    const fill = fragrance.querySelector('.gapbar i')!;
    expect(fill.getAttribute('data-shop')).toBe('shop_b');
    expect(fill.getAttribute('data-at')).toBe('start');
    expect(fill.getAttribute('style')).toContain(`background: ${retailerColor('shop_b', 1)}`);
    expect(within(fragrance).getByText('lower typical price at Shop B')).toBeTruthy();
    expect(within(fragrance.cells[3]!).queryByText(/cheaper/)).toBeNull();
    expect(row('Lips').querySelector('.gapbar i')?.getAttribute('data-shop')).toBe('shop_a');
    expect(document.querySelector('[data-side], .text-good, .text-bad')).toBeNull();
    expect(row('Body').querySelector('.gapbar i')?.getAttribute('style')).toContain('width: 50%');
  });

  it('the matched column: the shop cheaper on more of the category’s pairs, k of n, the counts in a tip', () => {
    const { row, tipOf } = show(ready());
    const fragrance = row('Fragrance').cells[4]!;
    expect(face(fragrance)).toBe('Shop B30 of 42');
    expect(tipOf(fragrance.querySelector('[aria-describedby]')!)).toBe(
      'Matched pairs in the category: Shop A cheaper on 10, Shop B on 30, same price on 2.',
    );
    expect(face(row('Skincare').cells[4]!)).toBe('Shop A12 of 16');
    cleanup();
    show(ready(), groups({ ...GROUPS, skincare: [6, 6, 1] }));
    expect(face(screen.getByRole<HTMLTableRowElement>('row', { name: /^Skincare/ }).cells[4]!)).toBe(
      'even, 6 each of 13',
    );
  });

  it('a figure below the minimum is a dash with the count in its tip, never a number in the cell', () => {
    const { row, tipOf } = show(ready(), groups({ ...GROUPS, concealer: [4, 3, 0] }));
    const concealer = row('Concealer');
    const thin = concealer.cells[2]!;
    expect(face(thin)).toBe('–');
    expect(tipOf(thin.querySelector('[aria-describedby]')!)).toBe('Not enough products: 3 priced, needs 5.');
    // Cheek prices compare, but its 3 matched pairs are under the minimum.
    const cheek = row('Cheek').cells[4]!;
    expect(face(cheek)).toBe('–');
    expect(tipOf(cheek.querySelector('[aria-describedby]')!)).toBe('Not enough matches: 3 matched, needs 5.');
    // A category with no group at all has no matches, not a count the API never sent.
    expect(tipOf(row('Body').cells[4]!.querySelector('[aria-describedby]')!)).toBe(
      'Not enough matches: none, needs 5.',
    );
  });

  it('categories with neither read fold into one last row, each with its counts in the tip', () => {
    const { tipOf } = show(ready());
    const fold = screen.getByText('1 more category: not enough data');
    expect(tipOf(fold.parentElement!)).toBe('Concealer: Shop A 104 priced · Shop B 3 priced · no matches');
  });

  it('a side the API left out is "not available", never a count of 0', () => {
    const r = ready();
    const buckets = r.data.buckets.map((b) =>
      b.key === 'cheek'
        ? { ...b, sides: { shop_a: b.sides.shop_a! }, status: 'too_few' as const, gapPct: null }
        : b,
    );
    const { row, tipOf } = show(
      { ...r, data: { ...r.data, buckets } },
      groups({ ...GROUPS, cheek: [5, 1, 0] }),
    );
    const cell = row('Cheek').cells[2]!;
    expect(face(cell)).toBe('–');
    expect(tipOf(cell.querySelector('[aria-describedby]')!)).toBe('not available');
    expect(row('Cheek').textContent).not.toContain('n = 0');
  });

  it('live shape: not_enough_data with every row still draws the matched rows, not "not available"', () => {
    const { row } = show(stale());
    expect(screen.getAllByRole('rowheader').map((h) => h.textContent)).toEqual([
      'Fragrance',
      'Skincare',
      'Lips',
    ]);
    expect(face(row('Fragrance').cells[1]!)).toBe('–');
    expect(face(row('Fragrance').cells[4]!)).toBe('Shop B30 of 42');
    expect(screen.getByText('6 more categories: not enough data')).toBeTruthy();
    expect(document.body.textContent).not.toContain('not available yet');
  });

  it('with no row to show the card is not drawn at all, and the Overview knows it', () => {
    expect(show({ kind: 'empty', env: null }, null).container.innerHTML).toBe('');
    cleanup();
    expect(show(stale(), groups({ cheek: 3 })).container.innerHTML).toBe('');
    expect(hasCategoryRows(stale(), groups({ cheek: 3 }))).toBe(false);
    expect(hasCategoryRows(stale(), groups())).toBe(true);
    expect(hasCategoryRows({ kind: 'loading' }, null)).toBe(true);
  });

  it('without the matched read: no matched column and the plain title', () => {
    show(ready(), null);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Where each shop is cheaper');
    expect(screen.queryByRole('columnheader', { name: 'Same product cheaper at' })).toBeNull();
    expect(screen.getAllByRole('rowheader')).toHaveLength(8);
  });

  it('error says so with a retry', () => {
    show({ kind: 'error', error: new Error('x'), retry: () => {} });
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: /retry|try again/i })).toBeTruthy();
  });

  it('in Arabic, with Latin digits', () => {
    const { row } = show(ready(), groups(), 'ar');
    expect(
      screen.getByRole('heading', { level: 2, name: 'المنتج نفسه أرخص في Shop B في 2 من 3 فئات' }),
    ).toBeTruthy();
    expect(row('العطور').textContent).toContain('395.00');
    expect(face(row('العطور').cells[4]!)).toBe('Shop B30 من 42');
    expect(screen.getByText('السعر المعتاد (كل التشكيلة)').closest('th')).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/[٠-٩]/);
  });
});
