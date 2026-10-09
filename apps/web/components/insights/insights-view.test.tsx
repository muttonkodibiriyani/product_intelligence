import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
let apiVersion = '1.23.0';
const asked: Array<{ path: string; query: unknown }> = [];
const push = vi.fn();
vi.mock('../auth-provider', () => ({
  useAuth: () => ({
    api: {
      get: async (path: string, options?: { query?: unknown }) => {
        asked.push({ path, query: options?.query });
        const a = answers[path];
        if (a instanceof Error) throw a;
        return typeof a === 'function' ? (a as (q: unknown) => unknown)(options?.query) : a;
      },
    },
  }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/en/insights/',
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock('../use-meta', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../use-meta')>()),
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
  apiVersion = '1.23.0';
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
    '/api/v1/products/{product_id}': new ApiError('not_found', 404),
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
/** One of the value, size-step and discount cards, by its title. */
const card = (name: string) => screen.getByRole('heading', { level: 3, name }).closest('article')!;
const barWidth = (el: HTMLElement, shop: string) =>
  Number.parseFloat(
    (el.querySelector<HTMLElement>(`[data-shop="${shop}"]`)?.style.width ?? '').replace('%', ''),
  );
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
      'Shop A: value, size steps and discounts',
    ]);
    const cards = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(cards.slice(-3)).toEqual([s.value.title, s.ladder.title, s.promo.title]);
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

  it('stock: "+N more brands" counts every qualifying brand, not only the ones the API lists', async () => {
    const many: Env = {
      ...rich,
      data: {
        ...rich.data!,
        stockouts: rich.data!.stockouts.map((r) =>
          r.retailer === 'shop_b'
            ? {
                ...r,
                qualifying: 30,
                brands: Array.from({ length: 12 }, (_, i) => ({
                  brand: `B${i}`,
                  observed: 20,
                  outOfStock: 10,
                })),
              }
            : r,
        ),
      },
    };
    view(many);
    await ready();
    const stock = section(s.stock.title);
    expect(await within(stock).findByText('+25 more brands')).toBeTruthy();
  });

  it('an answer that stopped early says its reason for each shop, never "not collected"', async () => {
    const early: Env = {
      ...rich,
      status: 'not_enough_data',
      reason: 'not_applicable',
      data: { ...rich.data!, stockouts: [], value: [] },
    };
    view(early);
    await ready();
    const stock = section(s.stock.title);
    expect(await within(stock).findAllByText(en.reasons.not_applicable)).toHaveLength(2);
    expect(stock.textContent).not.toContain('not collected');
    const value = card(s.value.title);
    expect(within(value).getAllByText(en.reasons.not_applicable).length).toBeGreaterThan(0);
    expect(value.textContent).not.toContain(en.insights.value.off);
  });

  it('a missing row in an answer with no reason reads "not in this answer"', async () => {
    view({ ...rich, data: { ...rich.data!, stockouts: [] } });
    await ready();
    expect(await within(section(s.stock.title)).findAllByText(en.insights.notInAnswer)).toHaveLength(2);
  });

  it('value: a shop without enough rated products says why in its chart row', async () => {
    status = { shop_a: 'supported', shop_b: 'partial', shop_c: 'partial' };
    view(rich);
    await ready();
    const value = card(s.value.title);
    expect(await within(value).findByText(en.reasons.cohort_too_small)).toBeTruthy();
  });

  it('value: picks as a share of rated listings, category tabs, three rows, notes in the tooltip', async () => {
    view(rich);
    await ready();
    const value = card(s.value.title);
    // Shop A is the focus (the first shop): 3 + 7 picks of 27 + 70 listings with 20+ ratings.
    expect(value.textContent).toContain('10value picks at Shop A');
    expect(value.textContent).toContain('10.3% · 10 of 97');
    expect(within(value).getByText(s.value.few)).toBeTruthy();
    const tabs = within(value).getByRole('group', { name: s.value.title });
    expect(within(tabs).getByRole('button', { name: 'Fragrance' }).getAttribute('aria-pressed')).toBe('true');
    expect(value.textContent).toMatch(/Typical .*6\.50.* per ml/);
    expect(within(value).getAllByRole('link', { name: /Daisy/i })).toHaveLength(1);
    expect(value.textContent).toMatch(/AED.*5\.15.* per ml · .*AED.*60\.00/);
    fireEvent.click(within(tabs).getByRole('button', { name: 'Lips' }));
    expect(value.textContent).toMatch(/Typical shelf price .*80\.00/);
    expect(within(value).getAllByRole('link', { name: /Lip \d$/ })).toHaveLength(3);
    const all = within(value).getByRole('link', { name: 'See all Lips at Shop A' });
    expect(hrefOf(all)).toContain('category=lips');
    expect(hrefOf(all)).toContain('retailer=shop_a');
    const tip = within(value).getByRole('tooltip').textContent;
    expect(tip).toContain('Fragrance 27/1426; Lips 70/100');
    expect(tip).toContain('Left out by the rules: Fragrance 1; Lips 4.');
  });

  it('size steps: the median saving, the steps not cheaper per ml and the smaller-size-on-sale note', async () => {
    view(rich);
    await ready();
    const ladder = card(s.ladder.title);
    expect(ladder.textContent).toContain('10.0%median saving per ml or g');
    expect(ladder.textContent).toContain('10.0% · 9 steps');
    expect(ladder.textContent).toContain('+10.0% per ml · 30→50 ml · smaller size on sale');
    expect(hrefOf(within(ladder).getByRole('link', { name: /Fixture Beauty Gel/ }))).toContain('p50');
  });

  it('discounts: share of priced listings, the deepest once per name, a note where none is published', async () => {
    const promo = {
      ...promotions,
      data: {
        ...promotions.data!,
        items: [
          promotions.data!.items[0]!,
          { ...promotions.data!.items[0]!, id: 'dup' },
          ...promotions.data!.items.slice(1),
        ],
      },
    };
    status = { shop_a: 'supported', shop_b: 'partial', shop_c: 'partial' };
    view(rich, 'en', { '/api/v1/promotions': promo });
    await ready();
    const promoCard = card(s.promo.title);
    await waitFor(() => expect(promoCard.textContent).toContain('18.8% · 3 of 16'));
    expect(promoCard.textContent).toContain('3Shop A listings on discount');
    expect(promoCard.textContent).toContain(s.promo.noOriginal);
    expect(within(promoCard).getAllByRole('link', { name: /Product p05/ })).toHaveLength(1);
    expect(within(promoCard).getAllByRole('listitem')).toHaveLength(3);
    expect(promoCard.textContent).toContain('Deepest · −33.3%');
    expect(hrefOf(within(promoCard).getByRole('link', { name: 'See all 3 on discount' }))).toContain(
      '/en/promotions?retailer=shop_a',
    );
  });

  it('discounts: a shop with fewer discounts but a higher share gets the longer bar', async () => {
    const promo = {
      ...promotions,
      data: {
        ...promotions.data!,
        retailers: [
          {
            ...promotions.data!.retailers[0]!,
            n: 7200,
            onPromo: 458,
            share: null,
            reason: 'retailer_partial',
          },
          {
            ...promotions.data!.retailers[1]!,
            n: 107,
            onPromo: 107,
            share: null,
            reason: 'retailer_partial',
          },
        ],
      },
    };
    const priced = (q: { retailer?: string[] }) => ({
      ...products,
      data: { ...products.data!, total: q.retailer?.[0] === 'shop_a' ? 7200 : 1454 },
    });
    view(rich, 'en', { '/api/v1/promotions': promo, '/api/v1/products': priced });
    await ready();
    const promoCard = card(s.promo.title);
    await waitFor(() => expect(promoCard.textContent).toContain('7.4% · 107 of 1,454'));
    expect(promoCard.textContent).toContain('6.4% · 458 of 7,200');
    expect(promoCard.textContent).toContain('458Shop A listings on discount');
    expect(barWidth(promoCard, 'shop_b')).toBe(100);
    expect(barWidth(promoCard, 'shop_a')).toBeLessThan(barWidth(promoCard, 'shop_b'));
  });

  it('asks the Findings for the default pair, and for the picked shop against its rival', async () => {
    apiVersion = '1.24.0'; // FINDINGS_API
    view(rich);
    await ready();
    const findings = () => asked.filter((a) => a.path === '/api/v1/findings').map((a) => a.query);
    expect(findings()).toContainEqual({ focus: 'shop_a', rival: 'shop_b' });
    cleanup();
    asked.length = 0;
    search = 'shop=shop_b';
    view(rich);
    await ready();
    expect(findings()).toContainEqual({ focus: 'shop_b', rival: 'shop_a' });
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
    expect(screen.getByRole('heading', { level: 3, name: ar.insights.value.title })).toBeTruthy();
    // A signed percentage keeps its sign before the digits in Arabic: an isolated left-to-right run.
    const [depth] = await within(card(ar.insights.promo.title)).findAllByText('−33.3%');
    expect(depth!.closest('bdi')?.getAttribute('dir')).toBe('ltr');
    const head = within(section(ar.insights.stock.title)).getByRole('link', { name: '37' });
    expect(head.querySelector('bdi')?.getAttribute('dir')).toBe('ltr');
    expect(container.textContent).not.toMatch(/[٠-٩]/);
  });

  it('says so on an older API, and asks /insights nothing', () => {
    apiVersion = '1.22.0';
    view(rich);
    // The other note is the pilot pair's absence: this fixture's shops are shop_a to shop_c.
    expect(screen.getAllByRole('note').some((n) => n.textContent?.includes('1.23.0'))).toBe(true);
    expect(asked.some((a) => a.path === '/api/v1/insights')).toBe(false);
  });

  it('a 404 from /insights reads as not available yet, not an error', async () => {
    view(new ApiError('not_found', 404));
    expect(await screen.findByText(s.unavailableRoute)).toBeTruthy();
  });
});
