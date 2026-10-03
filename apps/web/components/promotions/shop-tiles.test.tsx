import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import type { Schemas } from '@/lib/api/types';
import en from '@/messages/en.json';
import ar from '@/messages/ar.json';
import { ShopTiles } from './shop-tiles';

afterEach(cleanup);

type Promo = Schemas['RetailerPromo'];
type Item = Schemas['PromoItem'];

const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(+amount * 100) });
const item = (id: string, retailer: string, depthPct: string): Item => ({
  id,
  name: `Product ${id}`,
  retailer,
  price: aed('80.00'),
  regular: aed('120.00'),
  depthPct,
});

const sephora: Promo = { retailer: 'sephora_me', n: 4790, onPromo: 881, share: '18.4', reason: null };
const ulta: Promo = { retailer: 'ulta_ae', n: 7316, onPromo: 0, share: null, reason: 'was_price_unverified' };
const items = [
  item('p1', 'sephora_me', '50.0'),
  item('p2', 'sephora_me', '44.0'),
  item('p3', 'other', '60.0'),
];
const name = (id: string) => ({ sephora_me: 'Sephora', ulta_ae: 'Ulta' })[id] ?? id;

function tiles(retailers: Promo[], list: Item[] = items, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
      <ShopTiles retailers={retailers} items={list} name={name} />
    </NextIntlClientProvider>,
  );
}

describe('ShopTiles', () => {
  it('a measured shop: share as the hero, priced and on-promo counts, the deepest cut in its list, a bar', () => {
    tiles([sephora]);
    const tile = screen.getByRole('listitem');
    expect(within(tile).getByText('18.4%')).toBeTruthy();
    expect(tile.textContent).toContain('4,790 priced products');
    expect(tile.textContent).toContain('881 products carry a lower price than their regular price.');
    // The deepest cut is Sephora's own deepest row, not another shop's.
    expect(tile.textContent).toContain('Deepest cut: −50.0%.');
    const bar = tile.querySelector('i[style]') as HTMLElement;
    expect(bar.style.width).toBe('18.4%');
    expect(bar.className).toContain('bg-sephora');
  });

  it('says nothing about depth when the list has none of the shop’s products', () => {
    tiles([sephora], [item('p9', 'other', '60.0')]);
    expect(screen.getByRole('listitem').textContent).not.toContain('Deepest cut');
    expect(screen.getByRole('listitem').textContent).toContain('18.4%');
  });

  it('an unmeasured shop: one state line, the API’s reason, a link to its prices; no number, no bar', () => {
    tiles([ulta]);
    const tile = screen.getByRole('listitem');
    expect(within(tile).getByText('Discounts not measured')).toBeTruthy();
    expect(tile.textContent).toContain(en.reasons.was_price_unverified);
    expect(within(tile).getByRole('link', { name: 'Products' }).getAttribute('href')).toMatch(
      /^\/en\/explore\/?\?retailer=ulta_ae$/,
    );
    expect(tile.textContent).not.toMatch(/\d%/);
    expect(tile.querySelector('i[style]')).toBeNull();
    expect(tile.textContent).not.toContain('7,316');
    expect(tile.textContent).not.toContain('not available');
  });

  it('a reason the app does not know is shown as the API sent it', () => {
    tiles([{ ...ulta, reason: 'new_reason' as Promo['reason'] }]);
    expect(screen.getByText('new_reason').getAttribute('lang')).toBe('en');
  });

  it('a share of 0.0 is a number, not a missing one', () => {
    tiles([{ ...sephora, onPromo: 0, share: '0.0' }], []);
    const tile = screen.getByRole('listitem');
    expect(within(tile).getByText('0.0%')).toBeTruthy();
    expect(tile.textContent).toContain('No product carries a lower price than its regular price.');
    expect((tile.querySelector('i[style]') as HTMLElement).style.width).toBe('0%');
  });

  it('renders nothing for an empty list of shops, and one tile per shop otherwise', () => {
    const { container } = tiles([]);
    expect(container.innerHTML).toBe('');
    cleanup();
    tiles([sephora, ulta]);
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByRole('list').getAttribute('aria-label')).toBe(en.promotions.shares);
  });

  it('Arabic: the same facts in Arabic, the numbers still left to right', () => {
    tiles([sephora, ulta], items, 'ar');
    const [s, u] = screen.getAllByRole('listitem');
    expect(within(s!).getByText('18.4%').getAttribute('dir')).toBe('ltr');
    expect(s!.textContent).toContain('أكبر خصم: −50.0%.');
    expect(u!.textContent).toContain('الخصومات غير مقيسة');
    expect(u!.textContent).toContain(ar.reasons.was_price_unverified);
    expect(within(u!).getByRole('link', { name: 'المنتجات' })).toBeTruthy();
  });

  it('a partly covered shop with discounts seen: the count as the hero, never a share, and why', () => {
    const partial: Promo = {
      retailer: 'ulta_ae',
      n: 7234,
      onPromo: 458,
      share: null,
      reason: 'retailer_partial',
    };
    tiles([partial], [item('u1', 'ulta_ae', '62.5')]);
    const tile = screen.getByRole('listitem');
    expect(within(tile).getByText('458')).toBeTruthy();
    expect(within(tile).getByText(/discounted products seen/)).toBeTruthy();
    expect(within(tile).getByText(/62\.5%/)).toBeTruthy();
    expect(tile.textContent).toContain(en.promotions.shareWithheld);
    expect(tile.textContent).toContain(en.reasons.retailer_partial);
    expect(within(tile).queryByText(/^\d+(\.\d+)?%$/, { selector: 'bdi' })).toBeNull();
    expect(within(tile).queryByText(en.promotions.notMeasuredShop)).toBeNull();
  });

  it('a partly covered shop with no price pair seen stays "not measured"', () => {
    tiles([{ retailer: 'sephora_me', n: 0, onPromo: 0, share: null, reason: 'retailer_partial' }], []);
    expect(screen.getByText(en.promotions.notMeasuredShop)).toBeTruthy();
  });

  it('the partly covered tile in Arabic', () => {
    const partial: Promo = {
      retailer: 'ulta_ae',
      n: 7234,
      onPromo: 458,
      share: null,
      reason: 'retailer_partial',
    };
    tiles([partial], [], 'ar');
    expect(screen.getByRole('listitem').textContent).toContain(ar.promotions.shareWithheld);
    expect(screen.getByRole('listitem').textContent).toContain(ar.reasons.retailer_partial);
  });
});
