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

function table(items: Schemas['ProductCard'][]) {
  render(
    <NextIntlClientProvider locale="en" messages={en} onError={() => {}}>
      <ProductTable
        items={items}
        retailers={['ulta_ae', 'sephora_me']}
        pair={null}
        name={(id) => names[id] ?? id}
        from=""
      />
    </NextIntlClientProvider>,
  );
  // The price cells, in retailer order, of the one product row.
  return within(screen.getAllByRole('row')[1]!).getAllByRole('cell').slice(0, 2);
}

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
