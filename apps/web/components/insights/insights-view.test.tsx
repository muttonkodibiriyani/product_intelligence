import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
import { golden } from '@/lib/api/golden';
import type { Envelope, Schemas } from '@/lib/api/types';
import type { Insights } from '@/lib/insights';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { InsightsView } from './insights-view';

type Env = Envelope<Insights>;
const base = golden('insights') as Env;
const compare = golden('compare') as Envelope<Schemas['Comparison']>;
const gaps = golden('assortment-gaps') as Envelope<Schemas['AssortmentGaps']>;
const promotions = golden('promotions') as Envelope<Schemas['Promotions']>;
const coverage = golden('coverage');
const products = golden('products') as Envelope<Schemas['ProductPage']>;

const money = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(Number(amount) * 100) });
const pick = (id: string, brand: string, name: string, extra: Record<string, unknown> = {}) => ({
  brand,
  id,
  image: null,
  name,
  price: money('60.00'),
  rating: '4.8',
  ratingCount: 120,
  scale: '5',
  ...extra,
});

/** The golden with every per-shop section fed: stock-outs, whole-brand outages, value, a size step. */
const rich: Env = {
  ...base,
  data: {
    ...base.data!,
    pricing: { ...base.data!.pricing, n: 0, status: 'not_enough_data', reason: 'matches_unreviewed' },
    stockouts: base.data!.stockouts.map((s) =>
      s.retailer === 'shop_b'
        ? {
            ...s,
            listed: 900,
            withStock: 800,
            outOfStock: 37,
            brands: [
              { brand: 'Half', observed: 12, outOfStock: 6 },
              { brand: 'Some', observed: 40, outOfStock: 4 },
            ],
            unavailableBrands: 2,
            unavailableListings: 113,
            unavailable: [{ brand: 'Balmain', observed: 100, outOfStock: 100 }],
          }
        : s,
    ),
    value: base.data!.value.map((v) =>
      v.retailer === 'shop_a'
        ? {
            ...v,
            categories: [
              {
                category: 'fragrance',
                basis: 'per_unit',
                unitMedians: [{ median: '6.50', n: 1426, unit: 'ml' }],
                excluded: 1,
                median: money('310.00'),
                picks: 3,
                priced: 1426,
                rated: 27,
                items: [
                  pick('f1', 'Marc Jacobs', 'Daisy Eau de Toilette', {
                    sizeValue: '100',
                    sizeUnit: 'ml',
                    unitPrice: '5.15',
                  }),
                  pick('f2', 'Marc Jacobs', 'Daisy  eau de toilette'),
                  pick('f3', 'Snif', 'Extra Whip Body Mist'),
                ],
              },
              {
                category: 'lips',
                excluded: 4,
                median: money('80.00'),
                picks: 7,
                priced: 100,
                rated: 70,
                items: ['1', '2', '3', '4', '5', '6', '7'].map((n) => pick(`l${n}`, 'Milani', `Lip ${n}`)),
              },
            ],
          }
        : v,
    ),
    ladders: base.data!.ladders.map((l) =>
      l.retailer === 'shop_a'
        ? {
            ...l,
            reason: null,
            steps: 9,
            notCheaper: 1,
            heldOut: 1,
            medianSavingPct: '10.0',
            exceptions: [
              {
                basis: 'name',
                brand: 'Fixture Beauty',
                family: '',
                name: 'Gel',
                smallerId: 'p30',
                largerId: 'p50',
                smallerValue: '30',
                largerValue: '50',
                unit: 'ml',
                smallerPrice: money('60.00'),
                largerPrice: money('110.00'),
                unitChangePct: '10.0',
                smallerOnSale: true,
              },
            ],
          }
        : l,
    ),
  } as Insights,
};

let answers: Record<string, unknown> = {};
let search = '';
let status: Record<string, string> = { shop_a: 'supported', shop_b: 'partial' };
let apiVersion = '1.22.0';
const asked: Array<{ path: string; query: unknown }> = [];
const push = vi.fn();
vi.mock('../auth-provider', () => ({
  useAuth: () => ({
    api: {
      get: async (path: string, options?: { query?: unknown }) => {
        asked.push({ path, query: options?.query });
        const a = answers[path];
        if (a instanceof Error) throw a;
        return a;
      },
    },
  }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/en/insights/',
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock('../use-meta', () => ({
  useRetailerName: () => (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B', shop_c: 'Shop C' })[id] ?? id,
  useMeta: () => ({
    data: {
      meta: { apiVersion },
      data: {
        retailers: Object.entries(status).map(([id, s]) => ({ id, name: id, status: s })),
      },
    },
  }),
}));

beforeEach(() => {
  search = '';
  status = { shop_a: 'supported', shop_b: 'partial' };
  apiVersion = '1.22.0';
  asked.length = 0;
  push.mockReset();
});
afterEach(cleanup);

function view(env: Env | Error, locale: 'en' | 'ar' = 'en', more: Record<string, unknown> = {}) {
  answers = {
    '/api/v1/insights': env,
    '/api/v1/compare': compare,
    '/api/v1/assortment-gaps': gaps,
    '/api/v1/promotions': promotions,
    '/api/v1/coverage': coverage,
    '/api/v1/products': products,
    ...more,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider
        locale={locale}
        messages={locale === 'ar' ? ar : en}
        onError={(e) => {
          throw e;
        }}
      >
        <InsightsView />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const section = (name: string | RegExp) =>
  screen.getByRole('heading', { level: 2, name }).closest('section')!;
/** Waits for /insights to answer: the per-shop sections render after it. */
const ready = (name: string = en.insights.stock.title) => screen.findByRole('heading', { level: 2, name });
const hrefOf = (el: HTMLElement) => decodeURIComponent(el.closest('a')!.getAttribute('href')!);
const s = en.insights;

describe('InsightsView', () => {
  it('shows the sections in the mock order, with no report banner or method panel', async () => {
    view(rich);
    await screen.findByRole('heading', { level: 2, name: s.stock.title });
    const titles = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(titles).toEqual([
      s.glance.title,
      s.prices.title,
      s.stock.title,
      s.value.title,
      s.ladder.title,
      s.promo.title,
    ]);
    expect(screen.queryByText(/tested, not promoted/i)).toBeNull();
  });

  it('glance tiles count what Products counts, each number opening its list', async () => {
    view(rich);
    await ready();
    const glance = section(s.glance.title);
    const total = await within(glance).findAllByRole('link', { name: String(products.data!.total) });
    expect(hrefOf(total[0]!)).toContain('/en/explore');
    expect(hrefOf(total[0]!)).toContain('retailer=shop_a');
    expect(within(glance).getAllByText(/As of/).length).toBe(2);
    const priced = asked.find(
      (a) => a.path === '/api/v1/products' && (a.query as { priceMin?: string }).priceMin,
    );
    expect(priced?.query).toMatchObject({ priceMin: '0', retailer: ['shop_a'], limit: 1 });
  });

  it('waits for reviewed matches and lists each pair, never a sum or a price number', async () => {
    status = { shop_a: 'supported', shop_b: 'partial', shop_c: 'partial' };
    view(rich);
    await ready();
    const prices = section(s.prices.title);
    expect(await within(prices).findByText(s.prices.waiting)).toBeTruthy();
    const pairs = within(prices).getAllByRole('link');
    expect(pairs).toHaveLength(3);
    expect(hrefOf(pairs[0]!)).toContain('/en/compare?');
    expect(asked.filter((a) => a.path === '/api/v1/insights').map((a) => a.query)).toEqual([
      { retailers: 'shop_a,shop_b' },
      { retailers: 'shop_a,shop_c' },
      { retailers: 'shop_b,shop_c' },
    ]);
    expect(asked.some((a) => a.path === '/api/v1/compare')).toBe(false);
  });

  it('shows the price cards for a pair with reviewed matches', async () => {
    view(base);
    await screen.findByRole('heading', { level: 2, name: s.stock.title });
    expect(within(section(s.prices.title)).queryByText(s.prices.waiting)).toBeNull();
    expect(await screen.findByRole('heading', { level: 3, name: /Shop A.*×.*Shop B/ })).toBeTruthy();
  });

  it('stock: counts only, the headline opens out-of-stock without unavailable brands', async () => {
    view(rich);
    await ready();
    const stock = section(s.stock.title);
    const head = await within(stock).findByRole('link', { name: '37' });
    const href = hrefOf(head);
    expect(href).toContain('retailer=shop_b');
    expect(href).toContain('availability=out_of_stock');
    expect(href).toContain('unavailableBrands=exclude');
    expect(stock.textContent).not.toMatch(/%/);
    expect(stock.textContent).not.toMatch(/sold out/i);
    expect(within(stock).getByText(/Source reports unavailable/)).toBeTruthy();
    expect(hrefOf(within(stock).getByRole('link', { name: '113' }))).toContain('unavailableBrands=only');
    expect(hrefOf(within(stock).getByRole('link', { name: 'Half' }))).toContain('brand=Half');
    expect(within(stock).getByText('6 of 12 out')).toBeTruthy();
  });

  it('stock: says when a shop collects none', async () => {
    const off: Env = {
      ...rich,
      data: {
        ...rich.data!,
        stockouts: rich.data!.stockouts.map((r) =>
          r.retailer === 'shop_a' ? { ...r, reason: 'capability_off' } : r,
        ),
      },
    };
    view(off);
    await ready();
    expect(
      await within(section(s.stock.title)).findByText('Stock is not collected for Shop A.'),
    ).toBeTruthy();
  });

  it('value: a shop without enough rated products says why', async () => {
    status = { shop_a: 'supported', shop_b: 'partial', shop_c: 'partial' };
    view(rich);
    await ready();
    const value = section(s.value.title);
    expect(await within(value).findByText(en.reasons.cohort_too_small)).toBeTruthy();
  });

  it('value: per-ml and shelf lines, the audit notes, one row per name, five picks at most', async () => {
    view(rich);
    await ready();
    const value = section(s.value.title);
    await within(value).findByRole('link', { name: 'Fragrance' });
    expect(within(value).getByText(/Typical .*6\.50.* per ml · 3 picks/)).toBeTruthy();
    expect(within(value).getByText(/Typical shelf price .*80\.00.* · 7 picks/)).toBeTruthy();
    expect(within(value).getByText('Few rated: 27 of 1,426 listings have 20+ ratings')).toBeTruthy();
    expect(within(value).queryByText(/Few rated: 70/)).toBeNull();
    expect(within(value).getByText('1 listing left out by the rules')).toBeTruthy();
    expect(within(value).getByText('4 listings left out by the rules')).toBeTruthy();
    expect(within(value).getAllByRole('link', { name: /Daisy/i })).toHaveLength(1);
    expect(value.textContent).toMatch(/AED.*60\.00.* · 100 ml · .*AED.*5\.15.* per ml/);
    expect(within(value).getAllByRole('link', { name: /^Lip \d$/ })).toHaveLength(5);
    expect(hrefOf(within(value).getByRole('link', { name: 'Lips' }))).toContain('category=lips');
  });

  it('size steps: the median saving and the smaller-size-on-sale badge', async () => {
    view(rich);
    await ready();
    const ladder = section(s.ladder.title);
    expect(await within(ladder).findByText(/saves a median/)).toBeTruthy();
    expect(within(ladder).getByText('smaller size on sale')).toBeTruthy();
  });

  it('discounts: once per product name, by category without the catch-all, links to the lists', async () => {
    const promo = {
      ...promotions,
      data: {
        ...promotions.data!,
        items: [
          promotions.data!.items[0]!,
          { ...promotions.data!.items[0]!, id: 'dup' },
          ...promotions.data!.items.slice(1),
        ],
        retailers: promotions.data!.retailers.map((r) => ({
          ...r,
          groups: [
            { key: 'skincare', kind: 'category', n: 14, onPromo: 3, share: '21.4' },
            { key: 'other', kind: 'category', n: 9, onPromo: 2, share: '22.2' },
          ],
        })),
      },
    };
    search = 'shop=shop_a';
    view(rich, 'en', { '/api/v1/promotions': promo });
    await ready();
    const card = section(s.promo.title);
    await within(card).findByText(s.promo.byCat);
    expect(within(card).getAllByRole('link', { name: promotions.data!.items[0]!.name })).toHaveLength(1);
    expect(hrefOf(within(card).getByRole('link', { name: 'Skincare' }))).toContain('category=skincare');
    expect(hrefOf(within(card).getByRole('link', { name: '3' }))).toContain('/en/promotions?');
    expect(within(card).queryByText(/Other/)).toBeNull();
    expect(hrefOf(within(card).getByRole('link', { name: /All discounts at Shop A/ }))).toContain(
      'retailer=shop_a',
    );
  });

  it('the selector narrows the page to one shop and writes it to the URL', async () => {
    search = 'shop=shop_b';
    view(rich);
    await ready();
    const stock = section(s.stock.title);
    await within(stock).findByRole('link', { name: '37' });
    expect(within(stock).queryByRole('heading', { level: 3, name: 'Shop A' })).toBeNull();
    const group = screen.getByRole('group', { name: s.shops });
    expect(
      within(group)
        .getByRole('button', { name: /Shop B/ })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    fireEvent.click(within(group).getByRole('button', { name: /Shop A/ }));
    expect(push).toHaveBeenCalledWith('/en/insights/?shop=shop_a', { scroll: false });
    fireEvent.click(within(group).getByRole('button', { name: s.all }));
    expect(push).toHaveBeenLastCalledWith('/en/insights/', { scroll: false });
  });

  it('caveats sit in (i) tooltips', async () => {
    view(rich);
    await screen.findByRole('heading', { level: 2, name: s.stock.title });
    const tips = screen.getAllByRole('tooltip').map((t) => t.textContent);
    expect(tips).toContain(s.stock.tip);
    expect(tips.some((t) => t?.startsWith('Rated at least 4.5 out of 5 by 20 or more shoppers'))).toBe(true);
    expect(screen.getAllByRole('img', { name: s.info }).length).toBeGreaterThan(4);
  });

  it('renders in Arabic with every message present and numbers in left-to-right runs', async () => {
    const { container } = view(rich, 'ar');
    await screen.findByRole('heading', { level: 2, name: ar.insights.stock.title });
    expect(screen.getByText(ar.insights.value.title)).toBeTruthy();
    const head = within(section(ar.insights.stock.title)).getByRole('link', { name: '37' });
    expect(head.querySelector('bdi')?.getAttribute('dir')).toBe('ltr');
    expect(container.textContent).not.toMatch(/[٠-٩]/);
  });

  it('says so on an older API, and asks /insights nothing', () => {
    apiVersion = '1.21.0';
    view(rich);
    expect(screen.getByRole('note').textContent).toContain('1.22.0');
    expect(asked.some((a) => a.path === '/api/v1/insights')).toBe(false);
  });

  it('a 404 from /insights reads as not available yet, not an error', async () => {
    view(new ApiError('not_found', 404));
    expect(await screen.findByText(s.unavailableRoute)).toBeTruthy();
  });
});
