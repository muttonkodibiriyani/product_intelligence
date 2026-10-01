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
  it('draws one card per product: name links to the product, a price per retailer it is offered at', () => {
    grid([card({}), card({ id: 'p2', name: 'Lip Kit', prices: { sephora_me: aed('90.00') } })]);
    const cards = screen.getAllByRole('listitem');
    expect(cards).toHaveLength(2);
    const first = within(cards[0]!);
    expect(first.getByRole('link', { name: 'Moisture Surge 100H' }).getAttribute('href')).toMatch(
      /^\/en\/product\/?\?id=p1$/,
    );
    expect(first.getByText('Ulta UAE')).toBeTruthy();
    expect(first.getByText(/120\.00/)).toBeTruthy();
    expect(within(cards[1]!).queryByText('Ulta UAE')).toBeNull();
  });

  it('shows "Price under review" for a price of 0.01 or less, never the number', () => {
    grid([card({ prices: { ulta_ae: aed('0.01'), sephora_me: aed('0.00') } })]);
    expect(screen.getAllByText(en.price.underReview)).toHaveLength(2);
    expect(screen.queryByText(/0\.01|0\.00/)).toBeNull();
  });

  it('a product without an image gets the named placeholder, not a broken image', () => {
    grid([card({ image: null })]);
    expect(screen.getByRole('img', { name: en.explore.noImage })).toBeTruthy();
  });

  it('a failed image falls back to the placeholder', () => {
    const url = 'https://media.alshaya.com/adobe/assets/x/as/SK-0_1.png?width=533&height=800';
    const { container } = grid([card({ image: url })]);
    const img = container.querySelector('img')!;
    expect(img.getAttribute('loading')).toBe('lazy');
    expect(img.getAttribute('referrerpolicy')).toBe('no-referrer');
    fireEvent.error(img);
    expect(screen.getByRole('img', { name: en.explore.noImage })).toBeTruthy();
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
