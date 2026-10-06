import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import type { Schemas } from '@/lib/api/types';
import en from '@/messages/en.json';
import { ProductTable } from './product-table';

afterEach(cleanup);

const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(+amount * 100) });
const card = (over: Partial<Schemas['ProductCard']>): Schemas['ProductCard'] => ({
  id: 'p1',
  brand: 'Clinique',
  name: 'Moisture Surge 100H',
  category: ['skincare', 'moisturiser'],
  image: null,
  gap: null,
  matches: [],
  prices: { ulta_ae: aed('120.00'), sephora_me: aed('125.00') },
  size: { unit: 'ml', value: '50' },
  sizeLabel: null,
  sizeSystem: null,
  ...over,
});
const names: Record<string, string> = { ulta_ae: 'Ulta UAE', sephora_me: 'Sephora UAE' };

function table(items: Schemas['ProductCard'][], pair: [string, string] | null = null) {
  render(
    <NextIntlClientProvider
      locale="en"
      messages={en}
      onError={(e) => {
        throw e;
      }}
    >
      <ProductTable
        items={items}
        retailers={['ulta_ae', 'sephora_me']}
        pair={pair}
        name={(id) => names[id] ?? id}
        from=""
      />
    </NextIntlClientProvider>,
  );
  // The price cells, in retailer order, of the one product row.
  return within(screen.getAllByRole('row')[1]!).getAllByRole('cell').slice(0, 2);
}

describe('ProductTable match review', () => {
  it('"Unreviewed match" under the name of an unreviewed row only', () => {
    table([
      card({ matchReview: 'unreviewed' }),
      card({ id: 'p2', name: 'Lip Kit', matchReview: 'reviewed' }),
    ]);
    const [, first, second] = screen.getAllByRole('row');
    expect(within(first!).getByText(en.productCard.unreviewedMatch)).toBeTruthy();
    expect(within(second!).queryByText(en.productCard.unreviewedMatch)).toBeNull();
  });
});

describe('ProductTable prices', () => {
  it('shows "Price under review" for a price of 0.01 or less, never the number', () => {
    const [ulta, sephora] = table([card({ prices: { ulta_ae: aed('0.01'), sephora_me: aed('0.00') } })]);
    expect(ulta!.textContent).toBe(en.price.underReview);
    expect(sephora!.textContent).toBe(en.price.underReview);
  });

  it("the API's invalid_low flag on a null price reads as under review, not as no price", () => {
    const [ulta, sephora] = table([
      card({ prices: { ulta_ae: null, sephora_me: aed('125.00') }, priceFlags: { ulta_ae: 'invalid_low' } }),
    ]);
    expect(ulta!.textContent).toBe(en.price.underReview);
    expect(sephora!.textContent).toMatch(/125\.00/);
    expect(screen.queryByText(en.product.noPrice)).toBeNull();
  });

  it('a null price without the flag keeps "no price"', () => {
    const [ulta] = table([card({ prices: { ulta_ae: null, sephora_me: aed('125.00') } })]);
    expect(ulta!.textContent).toBe(en.product.noPrice);
    expect(screen.queryByText(en.price.underReview)).toBeNull();
  });
});

describe('ProductTable with a pair', () => {
  const gap = (pct: string, cheaper: 'base' | 'other' | 'equal'): Schemas['ProductCard']['gap'] => ({
    base: 'ulta_ae',
    other: 'sephora_me',
    excludedReason: null,
    gap: { amount: aed('5.00'), cheaper, pct },
    sizeLabels: null,
  });

  it('the gap column: the signed amount and percentage, a bar scaled to the largest gap in the list', () => {
    table(
      [card({ gap: gap('25.0', 'base') }), card({ id: 'p2', gap: gap('-12.5', 'other') })],
      ['ulta_ae', 'sephora_me'],
    );
    const [a, b] = screen.getAllByRole('row').slice(1);
    expect(a!.textContent).toContain('+25.0%');
    expect(a!.textContent).toContain('Sephora UAE dearer');
    expect(b!.textContent).toContain('-12.5%');
    expect(b!.textContent).toContain('Sephora UAE cheaper');
    const bars = [a, b].map((r) => r!.querySelector('.gapbar > i') as HTMLElement);
    expect(bars[0]!.dataset.side).toBe('good');
    expect(bars[0]!.style.width).toBe('50%');
    expect(bars[1]!.dataset.side).toBe('bad');
    expect(bars[1]!.style.width).toBe('25%');
  });

  it('an uncounted pair says why instead of a number', () => {
    table(
      [card({ gap: { ...gap('0', 'equal')!, gap: null, excludedReason: 'match_unreviewed' } })],
      ['ulta_ae', 'sephora_me'],
    );
    const row = screen.getAllByRole('row')[1]!;
    expect(row.textContent).toContain(en.gap.notCounted);
    expect(row.textContent).toContain(en.gap.excluded.match_unreviewed);
    expect(row.querySelector('.gapbar')).toBeNull();
  });

  it('a shop that does not sell the product reads "Not sold", not "No price"', () => {
    const [ulta] = table([card({ prices: { sephora_me: aed('125.00') } })]);
    expect(ulta!.textContent).toBe(en.productCard.notSold);
  });
});
