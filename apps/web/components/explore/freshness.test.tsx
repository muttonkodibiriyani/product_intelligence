import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Envelope, Schemas } from '@/lib/api/types';
import { sourceFreshness } from '@/lib/source-freshness';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { Explorer } from './explorer';
import { ProductGrid } from './product-grid';
import { ProductTable } from './product-table';

const api = vi.hoisted(() => ({ page: vi.fn(), get: vi.fn() }));
const nav = vi.hoisted(() => ({ search: '' }));
vi.mock('../auth-provider', () => ({ useAuth: () => ({ api }) }));
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/en/explore/',
}));

const IDS = ['bloomingdales_ae', 'faces_ae', 'ounass_ae', 'sephora_me', 'ulta_ae'] as const;
const LAST: Record<(typeof IDS)[number], string> = {
  bloomingdales_ae: '2026-10-08',
  faces_ae: '2026-10-03',
  ounass_ae: '2026-10-07',
  sephora_me: '2026-10-01',
  ulta_ae: '2026-10-09',
};
const metaView = {
  dates: ['2026-10-01', '2026-10-03', '2026-10-07', '2026-10-08', '2026-10-09'],
  retailers: IDS.map((id) => ({ id, name: id, country: 'AE', note: null, since: null, status: 'supported' })),
  sources: IDS.map((id) => ({ source: id, lastDate: LAST[id], products: 1, fields: {} })),
} as unknown as Schemas['MetaView'];
vi.mock('../use-meta', () => ({
  useRetailerName: () => (id: string) => id,
  useMeta: () => ({ data: { status: 'ok', data: metaView, caveats: [], meta: {} } }),
}));

afterEach(() => {
  cleanup();
  api.page.mockReset();
  api.get.mockReset();
  nav.search = '';
  localStorage.clear();
});

const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(+amount * 100) });

/**
 * One page of 50 retailer-local rows (10 per retailer): every third has no brand, image, size or
 * category, every seventh no price on the read date. Each row carries only its own retailer price.
 */
function rows(): Schemas['ProductCard'][] {
  return Array.from({ length: 50 }, (_, i) => {
    const r = IDS[i % IDS.length]!;
    const bare = i % 3 === 0;
    return {
      id: `${r}:p${i}`,
      brand: bare ? '' : `Brand ${i}`,
      name: `Product ${i}`,
      category: bare ? [] : ['skincare'],
      image: null,
      gap: null,
      matches: [],
      prices: { [r]: i % 7 === 6 ? null : aed(`${10 + i}.00`) },
      size: bare ? null : { unit: 'ml', value: '50' },
      sizeLabel: null,
      sizeSystem: null,
    };
  });
}

function wrap(node: React.ReactNode, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'en' ? en : ar}
      timeZone="UTC"
      onError={(e) => {
        throw e;
      }}
    >
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <div dir={locale === 'ar' ? 'rtl' : 'ltr'}>{node}</div>
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

const sources = sourceFreshness(metaView);

describe('ProductTable evidence states', () => {
  it('keeps every row, labels missing fields and shows each retailer own state', () => {
    const items = rows();
    wrap(
      <ProductTable
        items={items}
        retailers={[...IDS]}
        pair={null}
        name={(id) => id}
        from=""
        sources={sources}
      />,
    );
    const all = screen.getAllByRole('row');
    expect(all).toHaveLength(51); // header + every product, none dropped
    const header = all[0]!;
    expect(header.querySelectorAll('[data-evidence-state]')).toHaveLength(5);
    expect(header.querySelector('[data-evidence-state="fresh"]')?.textContent).toContain(
      en.freshness.state.fresh,
    );
    expect(header.querySelectorAll('[data-evidence-state="stale"]')).toHaveLength(4);
    // Row 0 is Bloomingdale's with no brand/category/size/image: kept, every gap named.
    const first = all[1]!;
    expect(first.querySelector('[data-missing-fields]')?.getAttribute('data-missing-fields')).toBe(
      'brand category image size',
    );
    expect(within(first).getByText('Product 0')).toBeTruthy();
    // Other retailers' cells for a retailer-local row read "No offer observed", never a borrowed value.
    const cells = within(first).getAllByRole('cell');
    expect(cells.filter((c) => c.textContent === en.productCard.notSold)).toHaveLength(4);
    expect(cells[0]!.querySelector('[data-evidence-state="stale"]')).toBeTruthy();
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/out of stock|removed|delisted|not sold/i);
  });

  it('marks an invalid price as a price under review (not an invalid date) and a priceless cell without a state of its own', () => {
    const item = {
      ...rows()[4]!,
      prices: { ulta_ae: aed('0.01'), faces_ae: null },
      priceFlags: { ulta_ae: 'invalid_low' as const },
    };
    wrap(
      <ProductTable
        items={[item]}
        retailers={['ulta_ae', 'faces_ae']}
        pair={null}
        name={(id) => id}
        from=""
        sources={sources}
      />,
    );
    const [ulta, faces] = within(screen.getAllByRole('row')[1]!).getAllByRole('cell');
    const badge = ulta!.querySelector('[data-evidence-state="invalid_price"]');
    expect(badge?.textContent).toContain(en.freshness.state.invalid_price);
    expect(ulta!.textContent).not.toContain(en.freshness.state.invalid);
    expect(faces!.textContent).toBe(en.product.noPrice);
  });
});

describe('ProductGrid evidence states', () => {
  it('names an unnamed product and gives an absent gap a reason screen readers can read', () => {
    const items = rows().slice(0, 2);
    items[0] = { ...items[0]!, name: '' };
    wrap(
      <ProductTable
        items={items}
        retailers={[...IDS]}
        pair={['faces_ae', 'sephora_me']}
        name={(id) => id}
        from=""
        sources={sources}
      />,
    );
    const link = screen.getAllByRole('link')[0]!;
    expect(link.textContent).toBe(en.productCard.noName);
    const absent = document.querySelectorAll('[data-gap-absent]');
    expect(absent).toHaveLength(2);
    expect(absent[0]!.textContent).toContain(en.gap.noPair);
    expect(absent[0]!.querySelector('[aria-hidden]')?.textContent).toBe('–');
  });

  it('renders all 50 cards in Arabic with missing-field labels and non-latest states', () => {
    const items = rows();
    wrap(
      <ProductGrid items={items} retailers={[...IDS]} name={(id) => id} from="" sources={sources} />,
      'ar',
    );
    const cards = screen.getAllByRole('listitem');
    expect(cards).toHaveLength(50);
    expect(cards[0]!.querySelector('[data-missing-fields]')?.textContent).toContain(ar.freshness.field.brand);
    // Faces' priced card line carries its own stale state; Ulta's latest-date line carries none.
    expect(within(cards[1]!).getByText(ar.freshness.state.stale)).toBeTruthy();
    expect(cards[4]!.querySelector('[data-evidence-state]')).toBeNull();
    expect(within(cards[4]!).queryByText(ar.freshness.state.fresh)).toBeNull();
  });
});

describe('Explorer freshness', () => {
  const page = (items: Schemas['ProductCard'][]): Envelope<Schemas['ProductPage']> => ({
    status: 'ok',
    data: {
      facets: {
        retailer: IDS.map((key) => ({ key, count: 10 })),
        brand: [],
        category: [],
        attributes: {},
        attributesTruncated: [],
      } as unknown as Schemas['Facets'],
      items,
      nextCursor: 'c2',
      total: 120,
    },
    meta: { apiVersion: '1', currency: 'AED' } as Schemas['ApiMeta'],
    caveats: [],
  });

  it('shows every retailer state once and loads one bounded page with no per-product request', async () => {
    api.page.mockResolvedValue({ body: page(rows()), restarted: false });
    wrap(<Explorer />);
    expect(await screen.findAllByRole('listitem')).toBeTruthy();
    const strip = screen.getByRole('region', { name: en.freshness.title });
    expect(strip.querySelectorAll('[data-evidence-state]')).toHaveLength(5);
    expect(within(strip).getByText(/9 Oct 2026, the dataset's last date/)).toBeTruthy();
    expect(within(strip).getByText(/1 Oct 2026; the dataset runs to 9 Oct 2026/)).toBeTruthy();
    expect(api.page).toHaveBeenCalledTimes(1);
    expect(api.page.mock.calls[0]![1].query.limit).toBe(50);
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('says which missing-data products the active filters cannot match', async () => {
    nav.search = 'brand=Brand%201&priceMin=10&availability=in_stock';
    api.page.mockResolvedValue({ body: page(rows().slice(0, 1)), restarted: false });
    wrap(<Explorer />);
    const note = await screen.findByRole('note');
    expect(note.getAttribute('data-filter-gaps')).toBe('brand price availability');
    expect(note.textContent).toContain(en.freshness.gap.brand);
  });
});
