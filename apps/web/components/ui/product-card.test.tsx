import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import en from '@/messages/en.json';
import ar from '@/messages/ar.json';
import { monogram } from '../explore/row-thumb';
import { ProductCard, useVerdictChip, type Chip, type PriceLine } from './product-card';

afterEach(cleanup);

const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(+amount * 100) });
const lines: PriceLine[] = [
  { retailer: 'ulta_ae', label: 'Ulta UAE', price: aed('120.00') },
  { retailer: 'sephora_me', label: 'Sephora UAE', price: aed('125.00') },
];

function card(over: Partial<Parameters<typeof ProductCard>[0]> = {}, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
      <ProductCard
        href="/en/product/?id=p1"
        image={null}
        brand="Estée Lauder"
        name="Advanced Night Repair"
        size={{ unit: 'ml', value: '50' }}
        category="serum"
        lines={lines}
        {...over}
      />
    </NextIntlClientProvider>,
  );
}

describe('ProductCard', () => {
  it('picture (the monogram when there is none), brand, name as the link, size, a price per shop', () => {
    card();
    expect(screen.getByRole('img', { name: en.productCard.noImage }).textContent).toBe('EL');
    expect(screen.getByText('Estée Lauder')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Advanced Night Repair' }).getAttribute('href')).toMatch(
      /^\/en\/product\/?\?id=p1$/,
    );
    expect(screen.getByText('50 ml')).toBeTruthy();
    expect(screen.getByText('serum')).toBeTruthy();
    const terms = screen.getAllByRole('term').map((t) => t.textContent);
    expect(terms).toEqual(['Ulta UAE', 'Sephora UAE']);
    const prices = screen.getAllByRole('definition').map((d) => d.textContent);
    expect(prices[0]).toMatch(/120\.00/);
    expect(prices[1]).toMatch(/125\.00/);
  });

  it('a promotion line: the price now, the regular price struck through, and the depth as −%', () => {
    card({
      lines: [
        { retailer: 'ulta_ae', label: 'Ulta UAE', price: aed('75.00'), was: aed('120.00'), off: '37.5' },
      ],
    });
    const dd = screen.getByRole('definition');
    expect(dd.textContent).toMatch(/75\.00/);
    const was = dd.querySelector('s')!;
    expect(was.textContent).toMatch(/120\.00/);
    expect(within(was).getByText(en.productCard.was)).toBeTruthy();
    expect(screen.getByText('−37.5%')).toBeTruthy();
  });

  it('"Not sold", "Price under review" and "No price" lines, never a placeholder number', () => {
    card({
      lines: [
        { retailer: 'a', label: 'A', notSold: true },
        { retailer: 'b', label: 'B', price: aed('0.01') },
        { retailer: 'c', label: 'C', price: null, priceFlag: 'invalid_low' },
        { retailer: 'd', label: 'D', price: null },
      ],
    });
    expect(screen.getAllByRole('definition').map((d) => d.textContent)).toEqual([
      en.productCard.notSold,
      en.price.underReview,
      en.price.underReview,
      en.product.noPrice,
    ]);
    expect(screen.queryByText(/0\.01/)).toBeNull();
  });

  it('a product without a published name still links, and says the name is missing', () => {
    card({ name: '  ' });
    expect(screen.getByRole('link', { name: en.productCard.noName })).toBeTruthy();
  });

  it('the chip sits on the picture with its tone', () => {
    const chip: Chip = { tone: 'good', label: 'Ulta UAE cheaper 4.2%' };
    const { container } = card({ chip });
    const el = screen.getByText('Ulta UAE cheaper 4.2%');
    expect(el.className).toContain('verdict-good');
    expect(container.querySelector('.verdict-bad')).toBeNull();
  });

  it('binds a single-retailer image to that retailer and keeps a polished fallback', () => {
    const image = 'https://img-product.sephora.me/p1.jpg';
    const { rerender } = card({ image, imageRetailer: 'sephora_me' });
    const loaded = document.querySelector('img')!;
    expect(loaded.getAttribute('src')).toBe(image);
    expect(loaded.getAttribute('width')).toBe('320');
    expect(loaded.getAttribute('height')).toBe('320');
    expect(loaded.getAttribute('loading')).toBe('lazy');
    expect(loaded.getAttribute('decoding')).toBe('async');
    expect(loaded.getAttribute('referrerpolicy')).toBe('no-referrer');

    rerender(
      <NextIntlClientProvider locale="en" messages={en}>
        <ProductCard
          href="/en/product/?id=p1"
          image={image}
          imageRetailer="ulta_ae"
          brand="Estée Lauder"
          name="Advanced Night Repair"
          lines={lines}
        />
      </NextIntlClientProvider>,
    );
    expect(document.querySelector('img')).toBeNull();
    expect(screen.getByRole('img', { name: en.productCard.noImage }).textContent).toBe('EL');
  });

  it('in Arabic', () => {
    card({ lines: [{ retailer: 'a', label: 'أولتا', notSold: true }] }, 'ar');
    expect(screen.getByText(ar.productCard.notSold)).toBeTruthy();
    expect(screen.getByRole('img', { name: ar.productCard.noImage })).toBeTruthy();
  });
});

describe('useVerdictChip', () => {
  function Chips() {
    const chip = useVerdictChip((id) => ({ a: 'Shop A', b: 'Shop B' })[id] ?? id);
    const all = [
      chip({ kind: 'cheaper', retailer: 'b', pct: '12.5' }),
      chip({ kind: 'dearer', retailer: 'b', pct: '12.5' }),
      chip({ kind: 'same' }),
      chip({ kind: 'sizes' }),
      chip({ kind: 'review' }),
      chip({ kind: 'excluded', reason: 'match_unreviewed' }),
      chip(null),
    ];
    return (
      <ul>
        {all.map((c, i) => (
          <li key={i} data-tone={c?.tone ?? 'none'}>
            {c?.label}
          </li>
        ))}
      </ul>
    );
  }

  it('words every verdict with the shop name, in tone', () => {
    render(
      <NextIntlClientProvider
        locale="en"
        messages={en}
        onError={(e) => {
          throw e;
        }}
      >
        <Chips />
      </NextIntlClientProvider>,
    );
    const items = screen.getAllByRole('listitem');
    expect(items.map((li) => [li.dataset.tone, li.textContent])).toEqual([
      ['good', 'Shop B cheaper 12.5%'],
      ['good', 'Shop B 12.5% dearer'],
      ['neutral', en.productCard.same],
      ['neutral', en.productCard.sizesDiffer],
      ['warn', en.price.underReview],
      ['neutral', en.gap.excluded.match_unreviewed],
      ['none', ''],
    ]);
  });
});

describe('monogram', () => {
  it('initials of a multi-word brand, two letters of one word, a short all-caps brand whole', () => {
    expect(monogram('Estée Lauder')).toBe('EL');
    expect(monogram('Yves Saint Laurent')).toBe('YSL');
    expect(monogram('Charlotte Tilbury Beauty Ltd')).toBe('CTB');
    expect(monogram('Clinique')).toBe('CL');
    expect(monogram('NARS')).toBe('NARS');
    expect(monogram('MAC')).toBe('MAC');
    expect(monogram('  ')).toBe('');
  });
});
