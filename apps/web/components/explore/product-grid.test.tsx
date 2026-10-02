import { act, cleanup, fireEvent, render, renderHook, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import type { Schemas } from '@/lib/api/types';
import en from '@/messages/en.json';
import { ProductGrid, useView, ViewToggle } from './product-grid';

afterEach(() => {
  cleanup();
  localStorage.clear();
});

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

function grid(items: Schemas['ProductCard'][]) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} onError={() => {}}>
      <ProductGrid
        items={items}
        retailers={['ulta_ae', 'sephora_me']}
        pair={null}
        name={(id) => names[id] ?? id}
        from=""
      />
    </NextIntlClientProvider>,
  );
}

describe('ProductGrid', () => {
  it('draws one card per product: name links to the product, a line per shop, "Not sold" where it is not', () => {
    grid([card({}), card({ id: 'p2', name: 'Lip Kit', prices: { sephora_me: aed('90.00') } })]);
    const cards = screen.getAllByRole('listitem');
    expect(cards).toHaveLength(2);
    const first = within(cards[0]!);
    expect(first.getByRole('link', { name: 'Moisture Surge 100H' }).getAttribute('href')).toMatch(
      /^\/en\/product\/?\?id=p1$/,
    );
    expect(first.getByText('Ulta UAE')).toBeTruthy();
    expect(first.getByText(/120\.00/)).toBeTruthy();
    const second = within(cards[1]!);
    expect(second.getByText('Ulta UAE')).toBeTruthy();
    expect(second.getByText(en.productCard.notSold)).toBeTruthy();
    expect(second.getByText(/90\.00/)).toBeTruthy();
  });

  it('shows "Price under review" for a price of 0.01 or less, never the number', () => {
    grid([card({ prices: { ulta_ae: aed('0.01'), sephora_me: aed('0.00') } })]);
    expect(screen.getAllByText(en.price.underReview)).toHaveLength(2);
    expect(screen.queryByText(/0\.01|0\.00/)).toBeNull();
  });

  it("the API's invalid_low flag on a null price reads as under review, not as no price", () => {
    grid([
      card({ prices: { ulta_ae: null, sephora_me: aed('125.00') }, priceFlags: { ulta_ae: 'invalid_low' } }),
    ]);
    const ulta = screen.getByText('Ulta UAE').closest('div')!;
    expect(within(ulta).getByText(en.price.underReview)).toBeTruthy();
    expect(screen.queryByText(en.product.noPrice)).toBeNull();
    expect(screen.getByText(/125\.00/)).toBeTruthy();
  });

  it('a null price without the flag keeps "no price"', () => {
    grid([card({ prices: { ulta_ae: null, sephora_me: aed('125.00') } })]);
    expect(screen.getByText(en.product.noPrice)).toBeTruthy();
    expect(screen.queryByText(en.price.underReview)).toBeNull();
  });

  it('a shop that does not sell the product reads "Not sold" on its line', () => {
    grid([card({ prices: { sephora_me: aed('90.00') } })]);
    const ulta = screen.getByText('Ulta UAE').closest('div')!;
    expect(within(ulta).getByText(en.productCard.notSold)).toBeTruthy();
  });

  it("with a pair, the chip on the picture says how the other shop compares, by the API's percentage", () => {
    const pair = (a: string, b: string, cheaper: 'base' | 'other', pct: string, id: string) =>
      card({
        id,
        name: `Product ${id}`,
        prices: { ulta_ae: aed(a), sephora_me: aed(b) },
        gap: {
          base: 'ulta_ae',
          other: 'sephora_me',
          excludedReason: null,
          gap: { amount: aed((+b - +a).toFixed(2)), cheaper, pct },
          sizeLabels: ['30 ml', '75 ml'],
        },
      });
    grid([
      // The API's pct is a share of the base price, so with the base cheaper the other is "x% dearer":
      // 50 vs 150 is 200% dearer (the base is 66.7% cheaper, not 200%); 80 vs 100 is 25% dearer (not 20%).
      pair('50.00', '150.00', 'base', '200.0', 'p1'),
      pair('80.00', '100.00', 'base', '25.0', 'p2'),
      // The other way round the other shop is cheaper by that share: 150 vs 50, 100 vs 80.
      pair('150.00', '50.00', 'other', '-66.7', 'p3'),
      pair('100.00', '80.00', 'other', '-20.0', 'p4'),
    ]);
    const chipOf = (n: string) => within(screen.getByRole('link', { name: new RegExp(n) }).closest('li')!);
    expect(chipOf('Product p1').getByText('Sephora UAE 200.0% dearer')).toBeTruthy();
    expect(chipOf('Product p2').getByText('Sephora UAE 25.0% dearer')).toBeTruthy();
    expect(chipOf('Product p3').getByText('Sephora UAE cheaper 66.7%')).toBeTruthy();
    expect(chipOf('Product p4').getByText('Sephora UAE cheaper 20.0%')).toBeTruthy();
    expect(screen.queryByText(/Ulta UAE cheaper/)).toBeNull();
    // Each side's own size when the pair's sizes differ.
    expect(screen.getAllByText('30 ml')).toHaveLength(4);
    expect(screen.getAllByText('75 ml')).toHaveLength(4);
  });

  it('a product without an image gets the named placeholder, not a broken image', () => {
    grid([card({ image: null })]);
    expect(screen.getByRole('img', { name: en.productCard.noImage })).toBeTruthy();
  });

  it('a failed image falls back to the placeholder', () => {
    const url = 'https://media.alshaya.com/adobe/assets/x/as/SK-0_1.png?width=533&height=800';
    const { container } = grid([card({ image: url })]);
    const img = container.querySelector('img')!;
    expect(img.getAttribute('loading')).toBe('lazy');
    expect(img.getAttribute('referrerpolicy')).toBe('no-referrer');
    fireEvent.error(img);
    expect(screen.getByRole('img', { name: en.productCard.noImage })).toBeTruthy();
  });
});

describe('view choice', () => {
  it('is the grid until the reader picks the list, and the pick is remembered', () => {
    const { result } = renderHook(() => useView());
    expect(result.current[0]).toBe('grid');
    act(() => result.current[1]('list'));
    expect(result.current[0]).toBe('list');
    expect(renderHook(() => useView()).result.current[0]).toBe('list');
  });

  it('the toggle marks the current view pressed', () => {
    let picked = '';
    render(
      <NextIntlClientProvider locale="en" messages={en} onError={() => {}}>
        <ViewToggle view="grid" onChange={(v) => (picked = v)} />
      </NextIntlClientProvider>,
    );
    expect(screen.getByRole('button', { name: 'Grid' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'List' }));
    expect(picked).toBe('list');
  });
});
